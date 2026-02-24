import logging

from app.config import settings
from app.container import processor_service
from app.db import engine
from app.logging_utils import configure_json_logging, log_event
from app.metrics import inc_metric, metric_key, set_gauge_metric
from app.models import Base
from arq.connections import RedisSettings

configure_json_logging()
logger = logging.getLogger("worker")


async def startup(ctx):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await inc_metric(metric_key("worker.startup.count", service="worker"))
    log_event(logger, logging.INFO, "worker_startup_complete")


async def shutdown(ctx):
    return None


async def process_broadcast_job(ctx, payload: dict):
    user_id = str(payload.get("userId") or "")
    campaign_id = str(payload.get("campaignId") or "")
    await inc_metric(metric_key("worker.job.received", service="worker"))
    log_event(
        logger,
        logging.INFO,
        "broadcast_job_received",
        user_id=user_id,
        campaign_id=campaign_id,
    )
    result = await processor_service.process(payload)
    await inc_metric(metric_key("worker.job.completed", service="worker"))
    if bool(result.get("success")):
        await inc_metric(metric_key("worker.job.result", service="worker", outcome="success"))
    else:
        await inc_metric(metric_key("worker.job.result", service="worker", outcome="failed"))
    await set_gauge_metric(metric_key("worker.last_job_lag_ms", service="worker"), int(result.get("lagMs") or 0))
    log_event(
        logger,
        logging.INFO,
        "broadcast_job_completed",
        user_id=user_id,
        campaign_id=campaign_id,
        outcome=result.get("outcome"),
        success=bool(result.get("success")),
        count=int(result.get("count") or 0),
        lag_ms=int(result.get("lagMs") or 0),
    )
    return result


class WorkerSettings:
    functions = [process_broadcast_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = max(1, settings.broadcast_concurrency)
    poll_delay = 2.0
