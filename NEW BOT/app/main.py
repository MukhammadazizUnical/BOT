from contextlib import asynccontextmanager
import asyncio
import json
import logging
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.config import settings
from app.container import scheduler_service, userbot_service
from app.db import engine, db_session
from app.logging_utils import configure_json_logging
from app.metrics import global_prometheus_text, global_snapshot
from app.models import Base, TelegramAccount
from app.redis_client import redis_client
from app.schemas import HealthResponse, ReadyResponse, SendMessageDTO

configure_json_logging()
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.bot_role.strip().lower() == "app":
        await scheduler_service.start()

    try:
        yield
    finally:
        if settings.bot_role.strip().lower() == "app":
            await scheduler_service.stop()
        await userbot_service.cleanup_broadcast_clients()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


async def _database_ready() -> bool:
    async with db_session() as db:
        await db.execute(select(1))
    return True


async def _redis_ready() -> bool:
    pong = await redis_client.ping()
    return bool(pong)


async def _send_bot_text(chat_id: str, text: str) -> bool:
    if not settings.tg_bot_token:
        return False

    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")

    def _send_sync() -> dict:
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    try:
        result = await asyncio.to_thread(_send_sync)
        return bool(result.get("ok"))
    except Exception:
        logger.exception("Failed sending alert text via Telegram bot API")
        return False


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, role=settings.bot_role)


@app.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    db_ok = False
    redis_ok = False

    try:
        db_ok = await _database_ready()
    except Exception:
        db_ok = False

    try:
        redis_ok = await _redis_ready()
    except Exception:
        redis_ok = False

    if not (db_ok and redis_ok):
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "role": settings.bot_role,
                "database": db_ok,
                "redis": redis_ok,
            },
        )

    return ReadyResponse(ok=True, role=settings.bot_role, database=True, redis=True)


@app.get("/metrics")
async def metrics() -> dict:
    snapshot = await global_snapshot()
    return {
        "ok": True,
        "role": settings.bot_role,
        **snapshot,
    }


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
async def metrics_prometheus() -> PlainTextResponse:
    payload = await global_prometheus_text()
    return PlainTextResponse(payload)


@app.post("/bot/send")
async def send_message(payload: SendMessageDTO):
    if payload.user_id is None:
        raise HTTPException(status_code=400, detail="Bot API sender path is in bot_runner; pass user_id for userbot path.")

    telegram_account_id = payload.telegram_account_id
    if not telegram_account_id:
        async with db_session() as db:
            account = (
                await db.execute(
                    select(TelegramAccount)
                    .where(TelegramAccount.user_id == str(payload.user_id), TelegramAccount.is_active.is_(True))
                    .order_by(TelegramAccount.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if not account:
                raise HTTPException(status_code=400, detail="No active telegram account found for this user")
            telegram_account_id = account.id

    result = await userbot_service.send_message_to_user(
        user_id=payload.user_id,
        telegram_account_id=telegram_account_id,
        to=payload.to,
        message=payload.message,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result)
    return result


@app.post("/bot/send-bot")
async def send_bot_message(payload: SendMessageDTO):
    if not settings.tg_bot_token:
        raise HTTPException(status_code=500, detail="TG_BOT_TOKEN is missing")
    sent = await _send_bot_text(payload.to, payload.message)
    if not sent:
        raise HTTPException(status_code=500, detail={"success": False, "error": "telegram-send-failed"})
    return {"success": True}
