from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import db_session
from app.config import settings
from app.models import AllowedUser


class AccessService:
    def __init__(self):
        self.super_admins = {"mr_usmonovvvv", "sdezreg"}

    def normalize_username(self, username: str | None) -> str:
        return (username or "").strip().lstrip("@").lower()

    async def check_access(self, tg_user_id: int, username: str | None, first_name: str | None, last_name: str | None) -> tuple[bool, str | None]:
        if self.normalize_username(username) in self.super_admins:
            return True, None

        owner = (settings.owner_user_id or "").strip()
        if owner and str(tg_user_id) == owner:
            return True, None

        async with db_session() as db:
            now = datetime.utcnow()
            user = await db.get(AllowedUser, str(tg_user_id))
            if not user:
                try:
                    db.add(
                        AllowedUser(
                            id=str(tg_user_id),
                            username=username or first_name,
                            first_name=first_name,
                            last_name=last_name,
                            expires_at=now,
                        )
                    )
                except IntegrityError:
                    pass
                return False, "⛔ Ruxsat yo'q. Admin ga murojaat qiling: @Mr_usmonovvvv"

            if first_name and user.first_name != first_name:
                user.first_name = first_name
            if last_name and user.last_name != last_name:
                user.last_name = last_name
            if username and user.username != username:
                user.username = username

            if user.expires_at and now > user.expires_at:
                return False, "⚠️ Obuna vaqtingiz tugagan. Admin ga murojaat qiling: @Mr_usmonovvvv"

        return True, None
