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

    def admin_contact(self) -> str:
        username = self.normalize_username(settings.support_admin_username)
        if username:
            return f"@{username}"
        owner = (settings.owner_user_id or "").strip()
        return f"ID: {owner}" if owner else "admin"

    def first_time_denied_message(self) -> str:
        contact = self.admin_contact()
        return (
            "What can this bot do?\n\n"
            "🚀 Bot imkoniyatlari:\n\n"
            "✅ Siz a'zo bo'lgan barcha guruhlarga avtomatik xabar yuborish\n"
            "✅ Faqat o'zingiz tanlagan guruhlarga xabar yuborish\n"
            "✅ Matnli va rasmli xabarlarni yuborish\n"
            "✅ Xabar yuborish oralig'ini boshqarish\n\n"
            f"👤 Bot admini: {contact}"
        )

    def expired_denied_message(self) -> str:
        return f"⚠️ Obuna vaqtingiz tugagan. Admin ga murojaat qiling: {self.admin_contact()}"

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
                return False, self.first_time_denied_message()

            if first_name and user.first_name != first_name:
                user.first_name = first_name
            if last_name and user.last_name != last_name:
                user.last_name = last_name
            if username and user.username != username:
                user.username = username

            if user.expires_at and now > user.expires_at:
                return False, self.expired_denied_message()

        return True, None
