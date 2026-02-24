import asyncio
import logging
import random
import uuid

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.logging_utils import log_event
from app.metrics import inc_metric, metric_key, set_gauge_metric


class BroadcastQueueService:
    def __init__(self):
        self.redis_pool = None
        self.logger = logging.getLogger("broadcast_queue_service")

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
        interval_seconds: int | None = None,
        delay_ms: int = 0,
        job_id: str | None = None,
    ) -> str | None:
        pool = await self.get_pool()
        resolved_job_id = job_id or f"bc-{campaign_id}-{uuid.uuid4().hex[:10]}"
        _defer_by = delay_ms / 1000 if delay_ms > 0 else None
        queued = await pool.enqueue_job(
            "process_broadcast_job",
            {
                "userId": user_id,
                "message": message,
                "campaignId": campaign_id,
                "queuedAt": queued_at,
                "intervalSeconds": int(interval_seconds) if interval_seconds is not None else None,
            },
            _defer_by=_defer_by,
            _job_id=resolved_job_id,
        )
        if queued is None:
            await inc_metric(metric_key("queue.enqueue.result", service="queue", outcome="duplicate"))
            log_event(
                self.logger,
                logging.WARNING,
                "broadcast_enqueue_skipped_duplicate",
                user_id=user_id,
                campaign_id=campaign_id,
                job_id=resolved_job_id,
            )
            return None
        await inc_metric(metric_key("queue.enqueue.result", service="queue", outcome="success"))
        await set_gauge_metric(metric_key("queue.last_enqueue_delay_ms", service="queue"), int(delay_ms))
        log_event(
            self.logger,
            logging.INFO,
            "broadcast_enqueued",
            user_id=user_id,
            campaign_id=campaign_id,
            job_id=resolved_job_id,
            delay_ms=delay_ms,
        )
        return resolved_job_id

    @staticmethod
    def scheduled_job_id(user_id: str, campaign_id: str, run_slot: int) -> str:
        return f"bc-sched-{campaign_id}-{user_id}-{run_slot}"

    @staticmethod
    def continuation_job_id(user_id: str, campaign_id: str, due_slot_minute: int) -> str:
        return f"bc-cont-{campaign_id}-{user_id}-{due_slot_minute}"

    def continuation_delay_ms(self) -> int:
        jitter = random.randint(0, max(0, settings.broadcast_continuation_jitter_ms))
        return max(250, settings.broadcast_continuation_base_delay_ms) + jitter
