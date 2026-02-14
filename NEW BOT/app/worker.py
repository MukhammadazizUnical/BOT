from app.config import settings
from app.container import processor_service
from app.db import engine
from app.models import Base
from arq.connections import RedisSettings


async def startup(ctx):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def shutdown(ctx):
    return None


async def process_broadcast_job(ctx, payload: dict):
    return await processor_service.process(payload)


class WorkerSettings:
    functions = [process_broadcast_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = max(1, settings.broadcast_concurrency)
    poll_delay = 5.0
