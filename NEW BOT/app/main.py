from contextlib import asynccontextmanager
import asyncio
import json
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from app.config import settings
from app.container import scheduler_service, userbot_service
from app.db import engine, db_session
from app.models import Base, TelegramAccount
from app.schemas import HealthResponse, SendMessageDTO


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


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, role=settings.bot_role)


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

    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": payload.to, "text": payload.message}).encode("utf-8")

    def _send_sync():
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)

    try:
        result = await asyncio.to_thread(_send_sync)
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail={"success": False, "error": result})
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})
