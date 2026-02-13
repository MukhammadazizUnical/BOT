from sqlalchemy import select

from app.db import db_session
from app.models import Session, TelegramAccount


class SessionService:
    async def save_session(self, user_id: int, session_string: str) -> None:
        async with db_session() as db:
            existing = await db.get(Session, str(user_id))
            if existing:
                existing.session_string = session_string
            else:
                db.add(Session(user_id=str(user_id), session_string=session_string))

    async def get_session(self, user_id: int) -> str | None:
        async with db_session() as db:
            account = (
                await db.execute(
                    select(TelegramAccount)
                    .where(TelegramAccount.user_id == str(user_id), TelegramAccount.is_active.is_(True))
                    .order_by(TelegramAccount.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if account:
                return account.session_string

            any_account = (
                await db.execute(
                    select(TelegramAccount)
                    .where(TelegramAccount.user_id == str(user_id))
                    .order_by(TelegramAccount.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if any_account:
                return any_account.session_string

            legacy = await db.get(Session, str(user_id))
            return legacy.session_string if legacy else None

    async def has_session(self, user_id: int) -> bool:
        return (await self.get_session(user_id)) is not None
