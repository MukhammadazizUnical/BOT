from sqlalchemy import select

from app.db import db_session
from app.models import UserGroup


class GroupService:
    def _normalize_group_id(self, group_id: str, kind: str) -> str:
        raw = str(group_id)
        if kind != "supergroup":
            return raw
        if raw.startswith("-100"):
            return raw
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return raw
        return f"-100{digits}"

    async def get_groups(self, user_id: str, active_only: bool = True) -> list[UserGroup]:
        async with db_session() as db:
            query = select(UserGroup).where(UserGroup.user_id == user_id)
            if active_only:
                query = query.where(UserGroup.is_active.is_(True))
            query = query.order_by(UserGroup.created_at.desc())
            return list((await db.execute(query)).scalars().all())

    async def add_group(self, user_id: str, group_id: str, title: str, kind: str, access_hash: str | None = None) -> None:
        normalized_group_id = self._normalize_group_id(group_id, kind)
        async with db_session() as db:
            existing = (
                await db.execute(select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.id == normalized_group_id))
            ).scalars().first()
            if existing:
                existing.title = title
                existing.type = kind
                existing.access_hash = access_hash
                existing.is_active = True
            else:
                db.add(
                    UserGroup(
                        id=normalized_group_id,
                        user_id=user_id,
                        title=title,
                        type=kind,
                        access_hash=access_hash,
                        is_active=True,
                    )
                )

    async def remove_group(self, user_id: str, group_id: str) -> None:
        async with db_session() as db:
            existing = (
                await db.execute(select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.id == group_id))
            ).scalars().first()
            if existing:
                await db.delete(existing)
