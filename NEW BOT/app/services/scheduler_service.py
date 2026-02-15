import asyncio
from datetime import datetime

from sqlalchemy import exists, select

from app.config import settings
from app.db import db_session
from app.models import BroadcastConfig, TelegramAccount
from app.redis_client import redis_client
from app.services.broadcast_queue_service import BroadcastQueueService
from app.utils import deterministic_jitter_ms


class SchedulerService:
    def __init__(self, queue_service: BroadcastQueueService):
        self.queue_service = queue_service
        self._task: asyncio.Task | None = None
        self._running = False
        self.lock_key = "broadcast:scheduler:lock"
        self.lock_ttl_ms = 55000

    async def start(self) -> None:
        if self._task:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.check_and_run()
            except Exception:
                pass
            await asyncio.sleep(max(1, settings.scheduler_check_interval_ms // 1000))

    async def acquire_lock(self, token: str) -> bool:
        result = await redis_client.set(self.lock_key, token, px=self.lock_ttl_ms, nx=True)
        return bool(result)

    async def release_lock(self, token: str) -> None:
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        await redis_client.eval(script, 1, self.lock_key, token)

    async def check_and_run(self) -> None:
        token = f"scheduler-{datetime.utcnow().timestamp()}"
        if not await self.acquire_lock(token):
            return

        try:
            due = await self.get_due_configs(settings.scheduler_max_due_per_tick)
            if not due:
                return

            now = datetime.utcnow()
            queued_ids: list[int] = []
            for config in due:
                safe_interval = max(60, int(config.interval or 60))
                run_slot = int(now.timestamp() // safe_interval)
                delay = deterministic_jitter_ms(config.user_id, run_slot, settings.scheduler_jitter_max_ms)
                await self.queue_service.enqueue_send(
                    user_id=config.user_id,
                    message=config.message or "",
                    campaign_id=str(config.id),
                    queued_at=now.isoformat(),
                    delay_ms=delay,
                )
                queued_ids.append(config.id)

            if queued_ids:
                async with db_session() as db:
                    rows = (
                        await db.execute(select(BroadcastConfig).where(BroadcastConfig.id.in_(queued_ids)))
                    ).scalars().all()
                    for row in rows:
                        row.last_run_at = now
        finally:
            await self.release_lock(token)

    async def get_due_configs(self, limit: int) -> list[BroadcastConfig]:
        now = datetime.utcnow()
        early_factor = settings.scheduler_early_factor
        due: list[BroadcastConfig] = []
        async with db_session() as db:
            rows = (
                await db.execute(
                    select(BroadcastConfig)
                    .where(
                        BroadcastConfig.is_active.is_(True),
                        BroadcastConfig.message.is_not(None),
                        BroadcastConfig.interval.is_not(None),
                        exists(
                            select(TelegramAccount.id).where(
                                TelegramAccount.user_id == BroadcastConfig.user_id,
                                TelegramAccount.is_active.is_(True),
                            )
                        ),
                    )
                    .order_by(BroadcastConfig.last_run_at.asc().nullsfirst())
                    .limit(max(1, limit))
                )
            ).scalars().all()

            for row in rows:
                if row.interval is None:
                    continue
                threshold_seconds = max(60, int(row.interval * early_factor))
                if row.last_run_at is None:
                    due.append(row)
                    continue
                elapsed = (now - row.last_run_at).total_seconds()
                if elapsed >= threshold_seconds:
                    due.append(row)
        return due

    async def set_config(
        self,
        user_id: str,
        message: str | None = None,
        interval: int | None = None,
        is_active: bool | None = None,
    ) -> BroadcastConfig:
        async with db_session() as db:
            config = (
                await db.execute(select(BroadcastConfig).where(BroadcastConfig.user_id == user_id))
            ).scalars().first()
            if not config:
                config = BroadcastConfig(user_id=user_id, message=message or "", interval=interval or 3600, is_active=bool(is_active))
                db.add(config)
                return config

            if message is not None:
                config.message = message
            if interval is not None:
                config.interval = interval
            if is_active is not None:
                config.is_active = is_active
            return config

    async def get_config(self, user_id: str) -> BroadcastConfig | None:
        async with db_session() as db:
            return (
                await db.execute(select(BroadcastConfig).where(BroadcastConfig.user_id == user_id))
            ).scalars().first()
