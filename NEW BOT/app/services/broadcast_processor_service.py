import inspect
import logging
import random
from datetime import UTC, datetime

from app.config import settings
from app.db import db_session
from app.logging_utils import log_event
from app.metrics import inc_metric, metric_key, set_gauge_metric
from app.models import BroadcastConfig
from app.redis_client import redis_client
from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.userbot_service import UserbotService
from sqlalchemy import or_, select, update


class BroadcastProcessorService:
    def __init__(
        self, userbot_service: UserbotService, queue_service: BroadcastQueueService
    ):
        self.userbot_service = userbot_service
        self.queue_service = queue_service
        self.logger = logging.getLogger("broadcast_processor_service")

    async def acquire_user_lock(self, user_id: str, token: str) -> bool:
        key = f"broadcast:user-lock:{user_id}"
        maybe_result = redis_client.set(
            key, token, px=max(60000, settings.broadcast_user_lock_ttl_ms), nx=True
        )
        if inspect.isawaitable(maybe_result):
            result = await maybe_result
        else:
            result = maybe_result
        return bool(result)

    async def release_user_lock(self, user_id: str, token: str) -> None:
        key = f"broadcast:user-lock:{user_id}"
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        result = redis_client.eval(script, 1, key, token)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def resolve_cycle_anchor(queued_dt: datetime | None, started_at: datetime) -> datetime:
        return queued_dt if queued_dt is not None else started_at

    @staticmethod
    def utcnow_naive() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    async def process(self, payload: dict) -> dict:
        if settings.bot_role.strip().lower() != "worker":
            await inc_metric(metric_key("processor.skipped_non_worker", service="processor"))
            log_event(
                self.logger,
                logging.INFO,
                "broadcast_process_skipped_non_worker",
            )
            return {
                "success": True,
                "count": 0,
                "errors": [],
                "outcome": "skipped-non-worker",
            }

        user_id = str(payload.get("userId"))
        message = payload.get("message", "")
        campaign_id = payload.get("campaignId", "")
        queued_at = str(payload.get("queuedAt") or self.utcnow_naive().isoformat())
        payload_interval_seconds = int(payload.get("intervalSeconds") or 0)
        started_at = self.utcnow_naive()
        campaign_db_id = int(campaign_id) if str(campaign_id).isdigit() else None
        log_event(
            self.logger,
            logging.INFO,
            "broadcast_process_started",
            user_id=user_id,
            campaign_id=campaign_id,
        )
        await inc_metric(metric_key("processor.started", service="processor"))

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
                    (
                        await db.execute(
                            select(BroadcastConfig).where(
                                BroadcastConfig.user_id == user_id,
                                BroadcastConfig.id == campaign_db_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )

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

            if (
                payload_interval_seconds > 0
                and int(cfg.interval or 0) != payload_interval_seconds
            ):
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
            retry_delay = max(2000, self.queue_service.continuation_delay_ms())
            await self.queue_service.enqueue_send(
                user_id=user_id,
                message=message,
                campaign_id=campaign_id,
                queued_at=queued_at,
                interval_seconds=payload_interval_seconds
                if payload_interval_seconds > 0
                else None,
                delay_ms=retry_delay,
            )
            await inc_metric(metric_key("processor.lock_busy", service="processor"))
            log_event(
                self.logger,
                logging.INFO,
                "broadcast_process_lock_busy",
                user_id=user_id,
                campaign_id=campaign_id,
                retry_delay_ms=retry_delay,
            )
            return {
                "success": True,
                "count": 0,
                "errors": [],
                "error": "user-lock-busy",
                "outcome": "lock-busy",
                "continuationEnqueued": True,
                "continuationDelayMs": retry_delay,
                "continuationReason": "lock-busy-retry",
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
            continuation_enqueued = False
            continuation_delay_ms = None
            continuation_reason = None

            if campaign_db_id is not None and int(result.count or 0) > 0:
                cycle_anchor = self.resolve_cycle_anchor(queued_dt, started_at)
                async with db_session() as db:
                    await db.execute(
                        update(BroadcastConfig)
                        .where(
                            BroadcastConfig.user_id == user_id,
                            BroadcastConfig.id == campaign_db_id,
                            or_(
                                BroadcastConfig.last_run_at.is_(None),
                                BroadcastConfig.last_run_at < cycle_anchor,
                            ),
                        )
                        .values(last_run_at=cycle_anchor)
                    )

            if not result.success:
                summary = result.summary or {}
                pending = summary.get("pending", 0)
                in_flight = summary.get("inFlight", 0)
                if not result.error and (pending > 0 or in_flight > 0):
                    next_due_ms = int(summary.get("nextDueInMs", 0) or 0)
                    ready_pending_count = int(summary.get("readyPendingCount", 0) or 0)
                    if bool(summary.get("providerConstrainedDelay", False)):
                        if ready_pending_count > 0:
                            delay = self.queue_service.continuation_delay_ms()
                            continuation_reason = "ready-pending-fast"
                        elif next_due_ms > 0:
                            delay = next_due_ms
                            continuation_reason = "exact-next-due"
                        else:
                            delay = self.queue_service.continuation_delay_ms()
                            continuation_reason = "provider-fallback"
                    else:
                        if next_due_ms > 0:
                            delay = max(self.queue_service.continuation_delay_ms(), next_due_ms)
                        elif ready_pending_count > 0:
                            delay = self.queue_service.continuation_delay_ms()
                        else:
                            delay = max(5000, self.queue_service.continuation_delay_ms() * 3)
                        continuation_reason = "default-deferred"
                    await self.queue_service.enqueue_send(
                        user_id=user_id,
                        message=message,
                        campaign_id=campaign_id,
                        queued_at=queued_at,
                        interval_seconds=payload_interval_seconds
                        if payload_interval_seconds > 0
                        else None,
                        delay_ms=delay,
                    )
                    continuation_enqueued = True
                    continuation_delay_ms = delay

            summary = result.summary or {}
            failed = int(summary.get("failed", 0) or 0)
            sent_count = int(result.count or 0)
            pending = int(summary.get("pending", 0) or 0)
            in_flight = int(summary.get("inFlight", 0) or 0)
            is_failure = bool(result.error) or (failed > 0 and sent_count == 0)
            all_targets_sent = (
                not bool(result.error) and failed == 0 and pending == 0 and in_flight == 0
            )

            outcome = "sent"
            if result.error == "Faol Telegram akkaunt topilmadi":
                outcome = "no-account"
            elif is_failure:
                outcome = "failed"
            elif bool(summary.get("providerConstrainedDelay", False)):
                outcome = "provider-constrained-delay"
            elif pending > 0 or in_flight > 0:
                outcome = "deferred"

            log_event(
                self.logger,
                logging.INFO,
                "broadcast_process_result",
                user_id=user_id,
                campaign_id=campaign_id,
                outcome=outcome,
                success=not is_failure,
                all_targets_sent=all_targets_sent,
                count=sent_count,
                lag_ms=lag_ms,
                continuation_enqueued=continuation_enqueued,
                continuation_reason=continuation_reason,
            )
            await inc_metric(metric_key("processor.result.total", service="processor"))
            await inc_metric(metric_key("processor.result.by_outcome", service="processor", outcome=outcome))
            if not is_failure:
                await inc_metric(metric_key("processor.result.by_outcome", service="processor", outcome="success"))
            else:
                await inc_metric(metric_key("processor.result.by_outcome", service="processor", outcome="failed"))
            await set_gauge_metric(metric_key("processor.last_lag_ms", service="processor"), int(lag_ms))
            await set_gauge_metric(metric_key("processor.last_sent_count", service="processor"), int(sent_count))
            if continuation_enqueued:
                await inc_metric(
                    metric_key(
                        "processor.continuation.enqueued",
                        service="processor",
                        reason=(continuation_reason or "unknown"),
                    )
                )

            return {
                "success": not is_failure,
                "allTargetsSent": all_targets_sent,
                "count": sent_count,
                "errors": result.errors,
                "error": result.error,
                "summary": summary,
                "outcome": outcome,
                "continuationEnqueued": continuation_enqueued,
                "continuationDelayMs": continuation_delay_ms,
                "continuationReason": continuation_reason,
                "scheduledAt": queued_at,
                "startedAt": started_at.isoformat(),
                "lagMs": lag_ms,
            }
        finally:
            log_event(
                self.logger,
                logging.INFO,
                "broadcast_process_finished",
                user_id=user_id,
                campaign_id=campaign_id,
            )
            await self.release_user_lock(user_id, token)
