import random
from datetime import datetime

from app.config import settings
from app.db import db_session
from app.models import BroadcastConfig
from app.redis_client import redis_client
from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.userbot_service import UserbotService
from sqlalchemy import select, update


class BroadcastProcessorService:
    def __init__(self, userbot_service: UserbotService, queue_service: BroadcastQueueService):
        self.userbot_service = userbot_service
        self.queue_service = queue_service

    async def acquire_user_lock(self, user_id: str, token: str) -> bool:
        key = f"broadcast:user-lock:{user_id}"
        result = await redis_client.set(key, token, px=max(60000, settings.broadcast_user_lock_ttl_ms), nx=True)
        return bool(result)

    async def release_user_lock(self, user_id: str, token: str) -> None:
        key = f"broadcast:user-lock:{user_id}"
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        await redis_client.eval(script, 1, key, token)

    async def process(self, payload: dict) -> dict:
        if settings.bot_role.strip().lower() != "worker":
            return {
                "success": True,
                "count": 0,
                "errors": [],
                "outcome": "skipped-non-worker",
            }

        user_id = str(payload.get("userId"))
        message = payload.get("message", "")
        campaign_id = payload.get("campaignId", "")
        queued_at = str(payload.get("queuedAt") or datetime.utcnow().isoformat())
        payload_interval_seconds = int(payload.get("intervalSeconds") or 0)
        started_at = datetime.utcnow()
        campaign_db_id = int(campaign_id) if str(campaign_id).isdigit() else None

        def parse_iso(value: str) -> datetime | None:
            try:
                normalized = str(value).replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalized)
                return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            except Exception:
                return None

        queued_dt = parse_iso(queued_at)
        lag_ms = 0
        if queued_dt is not None:
            lag_ms = max(0, int((started_at - queued_dt).total_seconds() * 1000))

        if campaign_db_id is not None:
            async with db_session() as db:
                cfg = (
                    await db.execute(
                        select(BroadcastConfig).where(
                            BroadcastConfig.user_id == user_id,
                            BroadcastConfig.id == campaign_db_id,
                        )
                    )
                ).scalars().first()

            if not cfg or not cfg.is_active:
                return {
                    "success": True,
                    "count": 0,
                    "errors": [],
                    "error": "inactive-campaign",
                    "outcome": "inactive-campaign",
                    "scheduledAt": queued_at,
                    "startedAt": started_at.isoformat(),
                    "lagMs": lag_ms,
                }

            if (cfg.message or "") != str(message):
                return {
                    "success": True,
                    "count": 0,
                    "errors": [],
                    "error": "stale-payload",
                    "outcome": "stale-message",
                    "scheduledAt": queued_at,
                    "startedAt": started_at.isoformat(),
                    "lagMs": lag_ms,
                }

            if payload_interval_seconds > 0 and int(cfg.interval or 0) != payload_interval_seconds:
                return {
                    "success": True,
                    "count": 0,
                    "errors": [],
                    "error": "stale-payload",
                    "outcome": "stale-interval",
                    "scheduledAt": queued_at,
                    "startedAt": started_at.isoformat(),
                    "lagMs": lag_ms,
                }

        token = f"{campaign_id}-{random.randint(10000, 99999)}"
        lock = await self.acquire_user_lock(user_id, token)
        if not lock:
            return {
                "success": True,
                "count": 0,
                "errors": [],
                "error": "user-lock-busy",
                "outcome": "lock-busy",
                "scheduledAt": queued_at,
                "startedAt": started_at.isoformat(),
                "lagMs": lag_ms,
            }

        try:
            result = await self.userbot_service.broadcast_message(
                user_id=int(user_id),
                message_text=message,
                campaign_id=campaign_id,
                queued_at=queued_at,
                max_attempts_per_run=max(1, settings.broadcast_attempts_per_job),
            )

            if campaign_db_id is not None and int(result.count or 0) > 0:
                async with db_session() as db:
                    await db.execute(
                        update(BroadcastConfig)
                        .where(
                            BroadcastConfig.user_id == user_id,
                            BroadcastConfig.id == campaign_db_id,
                        )
                        .values(last_run_at=started_at)
                    )

            if not result.success:
                summary = result.summary or {}
                pending = summary.get("pending", 0)
                in_flight = summary.get("inFlight", 0)
                failed = summary.get("failed", 0)
                if not result.error and (pending > 0 or in_flight > 0) and failed == 0:
                    delay = max(
                        self.queue_service.continuation_delay_ms(),
                        int(summary.get("nextDueInMs", 0) or 0),
                    )
                    await self.queue_service.enqueue_send(
                        user_id=user_id,
                        message=message,
                        campaign_id=campaign_id,
                        queued_at=queued_at,
                        interval_seconds=payload_interval_seconds if payload_interval_seconds > 0 else None,
                        delay_ms=delay,
                    )

            summary = result.summary or {}
            failed = int(summary.get("failed", 0) or 0)
            sent_count = int(result.count or 0)
            is_failure = bool(result.error) or (failed > 0 and sent_count == 0)
            pending = int(summary.get("pending", 0) or 0)
            in_flight = int(summary.get("inFlight", 0) or 0)

            outcome = "sent"
            if result.error == "Faol Telegram akkaunt topilmadi":
                outcome = "no-account"
            elif is_failure:
                outcome = "failed"
            elif bool(summary.get("providerConstrainedDelay", False)):
                outcome = "provider-constrained-delay"
            elif pending > 0 or in_flight > 0:
                outcome = "deferred"

            return {
                "success": not is_failure,
                "count": sent_count,
                "errors": result.errors,
                "error": result.error,
                "summary": summary,
                "outcome": outcome,
                "scheduledAt": queued_at,
                "startedAt": started_at.isoformat(),
                "lagMs": lag_ms,
            }
        finally:
            await self.release_user_lock(user_id, token)
