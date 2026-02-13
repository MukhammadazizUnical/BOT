import random
from datetime import datetime

from app.config import settings
from app.redis_client import redis_client
from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.userbot_service import UserbotService


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
            return {"success": True, "count": 0, "errors": []}

        user_id = str(payload.get("userId"))
        message = payload.get("message", "")
        campaign_id = payload.get("campaignId", "")
        queued_at = str(payload.get("queuedAt") or datetime.utcnow().isoformat())

        token = f"{campaign_id}-{random.randint(10000, 99999)}"
        lock = await self.acquire_user_lock(user_id, token)
        if not lock:
            delay = self.queue_service.continuation_delay_ms()
            await self.queue_service.enqueue_send(
                user_id=user_id,
                message=message,
                campaign_id=campaign_id,
                queued_at=queued_at,
                delay_ms=delay,
            )
            return {"success": False, "count": 0, "errors": [], "error": "user-lock-busy"}

        try:
            result = await self.userbot_service.broadcast_message(
                user_id=int(user_id),
                message_text=message,
                campaign_id=campaign_id,
                queued_at=queued_at,
                max_attempts_per_run=max(1, settings.broadcast_attempts_per_job),
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
                        delay_ms=delay,
                    )

            return {
                "success": result.success,
                "count": result.count,
                "errors": result.errors,
                "error": result.error,
                "summary": result.summary,
            }
        finally:
            await self.release_user_lock(user_id, token)
