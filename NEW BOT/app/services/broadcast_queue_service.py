import asyncio
import random
import uuid

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings


class BroadcastQueueService:
    def __init__(self):
        self.redis_pool = None

    async def get_pool(self):
        if self.redis_pool is None:
            self.redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        return self.redis_pool

    async def enqueue_send(
        self,
        user_id: str,
        message: str,
        campaign_id: str,
        queued_at: str,
        delay_ms: int = 0,
    ) -> str:
        pool = await self.get_pool()
        job_id = f"bc-{campaign_id}-{uuid.uuid4().hex[:10]}"
        _defer_by = delay_ms / 1000 if delay_ms > 0 else None
        await pool.enqueue_job(
            "process_broadcast_job",
            {
                "userId": user_id,
                "message": message,
                "campaignId": campaign_id,
                "queuedAt": queued_at,
            },
            _defer_by=_defer_by,
            _job_id=job_id,
        )
        return job_id

    def continuation_delay_ms(self) -> int:
        jitter = random.randint(0, max(0, settings.broadcast_continuation_jitter_ms))
        return max(250, settings.broadcast_continuation_base_delay_ms) + jitter
