import asyncio
import logging
import uuid
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
)
from sqlalchemy import and_, func, or_, select, update

from app.config import settings
from app.db import db_session
from app.models import (
    BroadcastAttempt,
    BroadcastConfig,
    TelegramAccount,
    User,
    UserGroup,
)
from app.utils import (
    build_attempt_idempotency_key,
    classify_telegram_error,
    compute_retry_delay_ms,
    now_plus_ms,
    normalize_error_message,
    utcnow,
)


@dataclass
class BroadcastExecutionResult:
    success: bool
    count: int
    errors: list
    error: str | None = None
    summary: dict | None = None


class UserbotService:
    def __init__(self):
        self.logger = logging.getLogger("userbot_service")
        self.login_temp: dict[int, dict] = {}
        self.login_clients: dict[int, Client] = {}
        self.connected_clients: dict[str, Client] = {}
        self.peer_cache_warmed: set[str] = set()
        self.client_lock = asyncio.Lock()

        self.remote_groups_cache: dict[str, dict] = {}
        self.remote_groups_inflight: dict[str, asyncio.Task] = {}
        self.remote_groups_last_fetch_attempt: dict[str, int] = {}
        self.remote_groups_last_fetch_failure: dict[str, int] = {}

        self.metrics = defaultdict(int)

    @staticmethod
    def cycle_cutoff(now: datetime, cycle_interval_seconds: int) -> datetime:
        return now - timedelta(seconds=max(60, int(cycle_interval_seconds)))

    @staticmethod
    def is_interval_elapsed(
        sent_at: datetime | None, cycle_interval_seconds: int, now: datetime
    ) -> bool:
        if sent_at is None:
            return True
        required = max(60, int(cycle_interval_seconds))
        return (now - sent_at).total_seconds() >= required

    @staticmethod
    def is_retry_exhausted(next_retry_count: int, max_retries: int) -> bool:
        return next_retry_count > max_retries

    async def _ensure_user(self, user_id: int) -> None:
        async with db_session() as db:
            row = await db.get(User, str(user_id))
            if not row:
                db.add(User(id=str(user_id)))

    def _normalize_phone(self, raw_phone: str) -> str:
        value = str(raw_phone or "")
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits.startswith("00"):
            digits = digits[2:]
        return f"+{digits}" if digits else "+"

    def _normalize_code(self, raw_code: str) -> str:
        value = (raw_code or "").strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits

    def _normalize_remote_group_id(
        self, chat_id: int | str, chat_type: str | None
    ) -> str:
        raw = str(chat_id)
        type_value = str(chat_type or "").lower()
        is_supergroup = type_value == "supergroup" or type_value.endswith(".supergroup")
        if not is_supergroup:
            return raw
        if raw.startswith("-100"):
            return raw
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return raw
        return f"-100{digits}"

    async def _disconnect_login_client(self, user_id: int) -> None:
        client = self.login_clients.pop(user_id, None)
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    async def cancel_login(self, user_id: int) -> None:
        self.login_temp.pop(user_id, None)
        await self._disconnect_login_client(user_id)

    async def start_login(self, user_id: int, phone: str) -> dict:
        await self._ensure_user(user_id)
        await self._disconnect_login_client(user_id)
        normalized_phone = self._normalize_phone(phone)
        digits_only = "".join(ch for ch in normalized_phone if ch.isdigit())
        if len(digits_only) < 10 or len(digits_only) > 15:
            return {
                "success": False,
                "error": "Telefon raqam noto'g'ri formatda. Masalan: +998901234567",
            }

        temp_session_name = f"login_{user_id}_{int(time.time() * 1000)}"
        client = Client(
            name=temp_session_name,
            api_id=settings.tg_api_id,
            api_hash=settings.tg_api_hash,
            no_updates=True,
        )
        try:
            await client.connect()
            sent = await client.send_code(normalized_phone)
            self.login_temp[user_id] = {
                "phone": normalized_phone,
                "phone_code_hash": sent.phone_code_hash,
                "session_name": temp_session_name,
                "expired_retries": 0,
            }
            self.login_clients[user_id] = client
            return {"success": True}
        except FloodWait as fw:
            try:
                await client.disconnect()
            except Exception:
                pass
            return {"success": False, "error": "FLOOD_WAIT", "seconds": fw.value}
        except Exception as e:
            self.logger.exception(
                "start_login failed user_id=%s raw_phone=%r normalized_phone=%r",
                user_id,
                phone,
                normalized_phone,
            )
            try:
                await client.disconnect()
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    async def complete_login(self, user_id: int, phone: str, code: str) -> dict:
        temp = self.login_temp.get(user_id)
        if not temp:
            self.logger.warning(
                "complete_login missing temp session user_id=%s", user_id
            )
            return {
                "success": False,
                "error": "Login session not found",
                "errorCode": "LOGIN_SESSION_MISSING",
            }

        normalized_phone = temp.get("phone") or self._normalize_phone(phone)
        session_name = temp.get("session_name") or f"login_{user_id}"

        client = self.login_clients.get(user_id)
        transient_client = False
        disconnect_transient = False
        if client is None:
            client = Client(
                name=session_name,
                api_id=settings.tg_api_id,
                api_hash=settings.tg_api_hash,
                no_updates=True,
            )
            await client.connect()
            transient_client = True
            disconnect_transient = True
        try:
            if getattr(client, "is_connected", False) is False:
                await client.connect()
            normalized_code = self._normalize_code(code)
            if not normalized_code:
                return {"success": False, "error": "Kod noto'g'ri formatda"}

            me = await client.sign_in(
                normalized_phone, temp["phone_code_hash"], normalized_code
            )
            session_string = await client.export_session_string()
            await self._save_telegram_account(
                user_id, normalized_phone, me, session_string
            )
            self.login_temp.pop(user_id, None)
            if transient_client:
                await client.disconnect()
                disconnect_transient = False
            else:
                await self._disconnect_login_client(user_id)
            return {"success": True, "user": {"firstName": me.first_name or "User"}}
        except SessionPasswordNeeded:
            self.login_temp[user_id]["session_name"] = session_name
            if transient_client:
                self.login_clients[user_id] = client
                disconnect_transient = False
            return {"success": False, "requiresPassword": True}
        except PhoneCodeInvalid:
            if transient_client:
                self.login_clients[user_id] = client
                disconnect_transient = False
            return {
                "success": False,
                "error": "Kod noto'g'ri. Qayta urinib ko'ring.",
                "errorCode": "PHONE_CODE_INVALID",
            }
        except PhoneCodeExpired:
            if transient_client:
                await client.disconnect()
                disconnect_transient = False
            else:
                await self._disconnect_login_client(user_id)
            return {
                "success": False,
                "error": "Kod eskirgan. Loginni qayta boshlang.",
                "errorCode": "PHONE_CODE_EXPIRED",
            }
        except Exception as e:
            self.logger.warning(
                "complete_login failed user_id=%s phone=%s code_len=%s error=%s",
                user_id,
                normalized_phone,
                len(self._normalize_code(code)),
                str(e),
            )
            return {"success": False, "error": str(e)}
        finally:
            if transient_client and disconnect_transient:
                await client.disconnect()

    async def complete_2fa(self, user_id: int, phone: str, password: str) -> dict:
        temp = self.login_temp.get(user_id)
        if not temp:
            return {"success": False, "error": "Login session not found"}

        normalized_phone = temp.get("phone") or self._normalize_phone(phone)
        session_name = temp.get("session_name") or f"login_{user_id}"

        client = self.login_clients.get(user_id)
        transient_client = False
        disconnect_transient = False
        if client is None:
            client = Client(
                name=session_name,
                api_id=settings.tg_api_id,
                api_hash=settings.tg_api_hash,
                no_updates=True,
            )
            await client.connect()
            transient_client = True
            disconnect_transient = True
        try:
            if getattr(client, "is_connected", False) is False:
                await client.connect()
            me = await client.check_password(password)
            session_string = await client.export_session_string()
            await self._save_telegram_account(
                user_id, normalized_phone, me, session_string
            )
            self.login_temp.pop(user_id, None)
            if transient_client:
                await client.disconnect()
                disconnect_transient = False
            else:
                await self._disconnect_login_client(user_id)
            return {"success": True, "user": {"firstName": me.first_name or "User"}}
        except PasswordHashInvalid:
            if transient_client:
                self.login_clients[user_id] = client
                disconnect_transient = False
            return {"success": False, "error": "Parol noto'g'ri."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if transient_client and disconnect_transient:
                await client.disconnect()

    async def _save_telegram_account(
        self, user_id: int, phone: str, me, session_string: str
    ) -> None:
        async with db_session() as db:
            row = (
                await db.execute(
                    select(TelegramAccount).where(TelegramAccount.phone_number == phone)
                )
            ).scalar_one_or_none()
            if row:
                row.session_string = session_string
                row.user_id = str(user_id)
                row.is_active = True
                row.is_flood_wait = False
                row.flood_wait_until = None
                row.first_name = me.first_name
                row.last_name = me.last_name
                row.username = me.username
            else:
                db.add(
                    TelegramAccount(
                        id=str(uuid.uuid4()),
                        user_id=str(user_id),
                        phone_number=phone,
                        session_string=session_string,
                        first_name=me.first_name,
                        last_name=me.last_name,
                        username=me.username,
                        is_active=True,
                        is_flood_wait=False,
                    )
                )

    async def get_connected_client(
        self, user_id: int, account_id: str
    ) -> Client | None:
        async with self.client_lock:
            cached = self.connected_clients.get(account_id)
            if cached:
                return cached

            async with db_session() as db:
                account = await db.get(TelegramAccount, account_id)
                if not account or not account.is_active:
                    return None

                client = Client(
                    name=f"acc_{account.id}",
                    api_id=settings.tg_api_id,
                    api_hash=settings.tg_api_hash,
                    session_string=account.session_string,
                    in_memory=True,
                    no_updates=True,
                )
                await client.start()
                if account_id not in self.peer_cache_warmed:
                    try:
                        async for _ in client.get_dialogs():
                            pass
                        self.peer_cache_warmed.add(account_id)
                    except Exception as e:
                        self.logger.warning(
                            "peer cache warmup failed account_id=%s error=%s",
                            account_id,
                            str(e),
                        )
                self.connected_clients[account_id] = client
                return client

    async def cleanup_broadcast_clients(self) -> None:
        async with self.client_lock:
            for _, cli in self.connected_clients.items():
                try:
                    await cli.stop()
                except Exception:
                    pass
            self.connected_clients = {}
            self.peer_cache_warmed.clear()

    async def get_remote_groups(self, user_id: int) -> list[dict]:
        key = str(user_id)
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        ttl = settings.remote_groups_cache_ttl_ms
        min_refresh = settings.remote_groups_min_refresh_ms
        fail_cooldown = settings.remote_groups_failure_cooldown_ms
        effective_fresh = max(ttl, min_refresh)

        cached = self.remote_groups_cache.get(key)
        if cached and (now_ms - cached["fetched_at"] <= effective_fresh):
            return cached["groups"]

        inflight = self.remote_groups_inflight.get(key)
        if inflight:
            return await inflight

        last_attempt = self.remote_groups_last_fetch_attempt.get(key, 0)
        if cached and (now_ms - last_attempt < min_refresh):
            return cached["groups"]

        last_fail = self.remote_groups_last_fetch_failure.get(key, 0)
        if cached and (now_ms - last_fail < fail_cooldown):
            return cached["groups"]

        async def fetch_task() -> list[dict]:
            self.remote_groups_last_fetch_attempt[key] = now_ms
            try:
                groups = await self._fetch_remote_groups(user_id)
                self.remote_groups_cache[key] = {
                    "fetched_at": int(datetime.utcnow().timestamp() * 1000),
                    "groups": groups,
                }
                self.remote_groups_last_fetch_failure.pop(key, None)
                return groups
            except Exception:
                self.remote_groups_last_fetch_failure[key] = int(
                    datetime.utcnow().timestamp() * 1000
                )
                return cached["groups"] if cached else []
            finally:
                self.remote_groups_inflight.pop(key, None)

        task = asyncio.create_task(fetch_task())
        self.remote_groups_inflight[key] = task
        return await task

    async def _fetch_remote_groups(self, user_id: int) -> list[dict]:
        async with db_session() as db:
            account = (
                (
                    await db.execute(
                        select(TelegramAccount)
                        .where(
                            TelegramAccount.user_id == str(user_id),
                            TelegramAccount.is_active.is_(True),
                        )
                        .order_by(TelegramAccount.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )

        if not account:
            return []

        client = await self.get_connected_client(user_id, account.id)
        if not client:
            return []

        dialogs = [d async for d in client.get_dialogs()]
        result: list[dict] = []
        seen = set()
        for d in dialogs:
            chat = d.chat
            if not chat:
                continue
            type_value = str(chat.type).lower()
            is_group = type_value == "group" or type_value.endswith(".group")
            is_supergroup = type_value == "supergroup" or type_value.endswith(
                ".supergroup"
            )
            if not (is_group or is_supergroup):
                continue
            gid = self._normalize_remote_group_id(chat.id, chat.type)
            if gid in seen:
                continue
            seen.add(gid)
            result.append(
                {
                    "id": gid,
                    "title": chat.title or gid,
                    "type": "supergroup" if is_supergroup else "group",
                    "access_hash": None,
                }
            )
        return result

    async def send_message_to_user(
        self, user_id: int, telegram_account_id: str, to: str, message: str
    ) -> dict:
        client = await self.get_connected_client(user_id, telegram_account_id)
        if not client:
            return {"success": False, "error": "No active account"}
        try:
            await client.send_message(chat_id=to, text=message)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def recover_stuck_inflight_attempts(
        self, user_id: int, campaign_id: str
    ) -> int:
        cutoff = now_plus_ms(-settings.broadcast_inflight_stuck_ms)
        async with db_session() as db:
            result = await db.execute(
                update(BroadcastAttempt)
                .where(
                    BroadcastAttempt.user_id == str(user_id),
                    BroadcastAttempt.campaign_id == campaign_id,
                    BroadcastAttempt.status == "in-flight",
                    BroadcastAttempt.started_at <= cutoff,
                )
                .values(
                    status="pending",
                    next_attempt_at=utcnow(),
                    last_error="Recovered stuck in-flight",
                )
            )
            return result.rowcount or 0

    async def seed_campaign_attempts_if_needed(
        self,
        user_id: int,
        campaign_id: str,
        target_groups: Sequence[UserGroup],
        available_account_ids: list[str],
        max_retries: int,
    ) -> None:
        async with db_session() as db:
            rows = (
                await db.execute(
                    select(BroadcastAttempt.status, func.count(BroadcastAttempt.id))
                    .where(
                        BroadcastAttempt.user_id == str(user_id),
                        BroadcastAttempt.campaign_id == campaign_id,
                    )
                    .group_by(BroadcastAttempt.status)
                )
            ).all()
            total_existing = sum(r[1] for r in rows)
            active_existing = sum(
                r[1] for r in rows if r[0] in {"pending", "in-flight"}
            )

            if total_existing > 0 and active_existing > 0:
                return

            for idx, group in enumerate(sorted(target_groups, key=lambda x: x.id)):
                account_id = available_account_ids[idx % len(available_account_ids)]
                idem = build_attempt_idempotency_key(campaign_id, group.id)
                exists = (
                    await db.execute(
                        select(BroadcastAttempt.id).where(
                            BroadcastAttempt.idempotency_key == idem
                        )
                    )
                ).scalar_one_or_none()
                if exists:
                    continue
                db.add(
                    BroadcastAttempt(
                        id=str(uuid.uuid4()),
                        user_id=str(user_id),
                        campaign_id=campaign_id,
                        target_group_id=group.id,
                        assigned_account_id=account_id,
                        sequence=idx + 1,
                        status="pending",
                        retry_count=0,
                        max_retries=max_retries,
                        idempotency_key=idem,
                    )
                )

    async def broadcast_message(
        self,
        user_id: int,
        message_text: str,
        campaign_id: str,
        queued_at: str | None,
        max_attempts_per_run: int,
    ) -> BroadcastExecutionResult:
        max_retries = settings.broadcast_max_retries
        retry_base_ms = settings.broadcast_retry_base_ms
        retry_max_ms = settings.broadcast_retry_max_ms
        retry_jitter_ratio = settings.broadcast_retry_jitter_ratio

        per_account_delay_ms = max(
            settings.telegram_per_account_min_delay_ms,
            int(60000 / max(1, settings.telegram_per_account_mpm)),
        )

        async with db_session() as db:
            campaign_db_id = int(campaign_id) if str(campaign_id).isdigit() else None
            config = (
                (
                    await db.execute(
                        select(BroadcastConfig).where(
                            BroadcastConfig.user_id == str(user_id),
                            BroadcastConfig.id == campaign_db_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            active_accounts = (
                (
                    await db.execute(
                        select(TelegramAccount).where(
                            TelegramAccount.user_id == str(user_id),
                            TelegramAccount.is_active.is_(True),
                            or_(
                                TelegramAccount.is_flood_wait.is_(False),
                                TelegramAccount.flood_wait_until <= utcnow(),
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )

            target_groups = (
                (
                    await db.execute(
                        select(UserGroup)
                        .where(
                            UserGroup.user_id == str(user_id),
                            UserGroup.is_active.is_(True),
                        )
                        .order_by(UserGroup.id.asc())
                    )
                )
                .scalars()
                .all()
            )

        safety_seconds = max(0, int(settings.broadcast_interval_safety_seconds))
        cycle_interval_seconds = (
            max(60, int((config.interval if config and config.interval else 60)))
            + safety_seconds
        )

        if config is not None:
            sent_cutoff = self.cycle_cutoff(utcnow(), cycle_interval_seconds)
            async with db_session() as db:
                await db.execute(
                    update(BroadcastAttempt)
                    .where(
                        BroadcastAttempt.user_id == str(user_id),
                        BroadcastAttempt.campaign_id == campaign_id,
                        BroadcastAttempt.status == "sent",
                        BroadcastAttempt.sent_at.is_not(None),
                        BroadcastAttempt.sent_at <= sent_cutoff,
                    )
                    .values(
                        status="pending",
                        retry_count=0,
                        next_attempt_at=utcnow(),
                        started_at=None,
                        sent_at=None,
                        terminal_reason_code=None,
                        last_error=None,
                    )
                )
                await db.execute(
                    update(BroadcastAttempt)
                    .where(
                        BroadcastAttempt.user_id == str(user_id),
                        BroadcastAttempt.campaign_id == campaign_id,
                        BroadcastAttempt.status == "failed-terminal",
                        BroadcastAttempt.updated_at <= sent_cutoff,
                    )
                    .values(
                        status="pending",
                        retry_count=0,
                        next_attempt_at=utcnow(),
                        started_at=None,
                        terminal_reason_code=None,
                        last_error=None,
                    )
                )

        if not active_accounts:
            return BroadcastExecutionResult(
                success=False,
                count=0,
                errors=[],
                error="Faol Telegram akkaunt topilmadi",
            )

        if not target_groups:
            return BroadcastExecutionResult(success=True, count=0, errors=[])

        available_ids = [a.id for a in active_accounts]
        await self.recover_stuck_inflight_attempts(user_id, campaign_id)
        await self.seed_campaign_attempts_if_needed(
            user_id, campaign_id, list(target_groups), available_ids, max_retries
        )

        target_by_id = {g.id: g for g in target_groups}

        rate_lock = asyncio.Lock()
        timestamps: list[float] = []

        async def acquire_global_slot() -> None:
            async with rate_lock:
                while True:
                    now = datetime.utcnow().timestamp()
                    while timestamps and now - timestamps[0] >= 1:
                        timestamps.pop(0)
                    if len(timestamps) < settings.telegram_global_mps:
                        timestamps.append(now)
                        return
                    await asyncio.sleep(max(0.001, 1 - (now - timestamps[0])))

        budget_lock = asyncio.Lock()
        attempts_claimed = 0

        async def reserve_slot() -> bool:
            nonlocal attempts_claimed
            async with budget_lock:
                if attempts_claimed >= max(1, max_attempts_per_run):
                    return False
                attempts_claimed += 1
                return True

        async def run_attempt(attempt: BroadcastAttempt, account_id: str) -> None:
            client = await self.get_connected_client(user_id, account_id)
            if not client:
                async with db_session() as db:
                    await db.execute(
                        update(BroadcastAttempt)
                        .where(
                            BroadcastAttempt.id == attempt.id,
                            BroadcastAttempt.status == "in-flight",
                        )
                        .values(
                            status="pending",
                            next_attempt_at=now_plus_ms(30000),
                            last_error=f"Client unavailable for account {account_id}",
                        )
                    )
                return

            target = target_by_id.get(attempt.target_group_id)
            if not target:
                async with db_session() as db:
                    await db.execute(
                        update(BroadcastAttempt)
                        .where(
                            BroadcastAttempt.id == attempt.id,
                            BroadcastAttempt.status == "in-flight",
                        )
                        .values(
                            status="failed-terminal",
                            terminal_reason_code="missing-target",
                            last_error="Target group not found",
                        )
                    )
                return

            if attempt.sent_at is not None:
                if not self.is_interval_elapsed(
                    attempt.sent_at, cycle_interval_seconds, utcnow()
                ):
                    next_due = attempt.sent_at + timedelta(
                        seconds=cycle_interval_seconds
                    )
                    async with db_session() as db:
                        await db.execute(
                            update(BroadcastAttempt)
                            .where(
                                BroadcastAttempt.id == attempt.id,
                                BroadcastAttempt.status == "in-flight",
                            )
                            .values(status="pending", next_attempt_at=next_due)
                        )
                    return

            try:
                await acquire_global_slot()
                await client.send_message(chat_id=int(target.id), text=message_text)
                async with db_session() as db:
                    await db.execute(
                        update(BroadcastAttempt)
                        .where(
                            BroadcastAttempt.id == attempt.id,
                            BroadcastAttempt.status == "in-flight",
                        )
                        .values(
                            status="sent",
                            sent_at=utcnow(),
                            terminal_reason_code=None,
                            last_error=None,
                        )
                    )
            except Exception as e:
                err_msg = normalize_error_message(e)
                classified = classify_telegram_error(
                    e,
                    slowmode_default_seconds=settings.telegram_slowmode_default_seconds,
                )
                retry_count = attempt.retry_count + 1
                exhausted = self.is_retry_exhausted(retry_count, attempt.max_retries)

                if classified["retriable"] and not exhausted:
                    retry_delay_ms = compute_retry_delay_ms(
                        retry_count=retry_count,
                        retry_after_seconds=classified["retry_after_seconds"],
                        base_delay_ms=retry_base_ms,
                        max_delay_ms=retry_max_ms,
                        jitter_ratio=retry_jitter_ratio,
                    )
                    async with db_session() as db:
                        await db.execute(
                            update(BroadcastAttempt)
                            .where(
                                BroadcastAttempt.id == attempt.id,
                                BroadcastAttempt.status == "in-flight",
                            )
                            .values(
                                status="pending",
                                retry_count=retry_count,
                                next_attempt_at=now_plus_ms(retry_delay_ms),
                                last_error=err_msg,
                                terminal_reason_code="retriable-rate-limit",
                            )
                        )

                        if classified["retry_after_seconds"]:
                            await db.execute(
                                update(TelegramAccount)
                                .where(TelegramAccount.id == account_id)
                                .values(
                                    is_flood_wait=True,
                                    flood_wait_until=now_plus_ms(
                                        classified["retry_after_seconds"] * 1000
                                    ),
                                )
                            )
                else:
                    async with db_session() as db:
                        await db.execute(
                            update(BroadcastAttempt)
                            .where(
                                BroadcastAttempt.id == attempt.id,
                                BroadcastAttempt.status == "in-flight",
                            )
                            .values(
                                status="failed-terminal",
                                retry_count=retry_count,
                                terminal_reason_code=(
                                    "retry-exhausted"
                                    if exhausted
                                    else classified["terminal_code"]
                                ),
                                last_error=err_msg,
                            )
                        )

            await asyncio.sleep(per_account_delay_ms / 1000)

        worker_tasks = []

        async def lane(account_id: str):
            while True:
                reserved = await reserve_slot()
                if not reserved:
                    break

                async with db_session() as db:
                    attempt = (
                        (
                            await db.execute(
                                select(BroadcastAttempt)
                                .where(
                                    BroadcastAttempt.user_id == str(user_id),
                                    BroadcastAttempt.campaign_id == campaign_id,
                                    BroadcastAttempt.assigned_account_id == account_id,
                                    BroadcastAttempt.status == "pending",
                                    or_(
                                        BroadcastAttempt.next_attempt_at.is_(None),
                                        BroadcastAttempt.next_attempt_at <= utcnow(),
                                    ),
                                )
                                .order_by(
                                    BroadcastAttempt.sequence.asc(),
                                    BroadcastAttempt.created_at.asc(),
                                )
                                .limit(1)
                            )
                        )
                        .scalars()
                        .first()
                    )

                    if not attempt:
                        break

                    result = await db.execute(
                        update(BroadcastAttempt)
                        .where(
                            BroadcastAttempt.id == attempt.id,
                            BroadcastAttempt.status == "pending",
                        )
                        .values(
                            status="in-flight",
                            started_at=utcnow(),
                            assigned_account_id=account_id,
                        )
                    )

                    if (result.rowcount or 0) == 0:
                        continue

                await run_attempt(attempt, account_id)

        for account_id in available_ids:
            for _ in range(max(1, settings.broadcast_per_account_concurrency)):
                worker_tasks.append(asyncio.create_task(lane(account_id)))

        await asyncio.gather(*worker_tasks, return_exceptions=True)

        min_pending_next_attempt = None
        ready_pending_count = 0
        provider_constrained_pending = 0
        pending_reference_now = utcnow()
        async with db_session() as db:
            rows = (
                await db.execute(
                    select(BroadcastAttempt.status, func.count(BroadcastAttempt.id))
                    .where(
                        BroadcastAttempt.user_id == str(user_id),
                        BroadcastAttempt.campaign_id == campaign_id,
                    )
                    .group_by(BroadcastAttempt.status)
                )
            ).all()

            min_pending_next_attempt = (
                await db.execute(
                    select(func.min(BroadcastAttempt.next_attempt_at)).where(
                        BroadcastAttempt.user_id == str(user_id),
                        BroadcastAttempt.campaign_id == campaign_id,
                        BroadcastAttempt.status == "pending",
                        BroadcastAttempt.next_attempt_at.is_not(None),
                        BroadcastAttempt.next_attempt_at > pending_reference_now,
                    )
                )
            ).scalar_one_or_none()

            ready_pending_count = int(
                (
                    await db.execute(
                        select(func.count(BroadcastAttempt.id)).where(
                            BroadcastAttempt.user_id == str(user_id),
                            BroadcastAttempt.campaign_id == campaign_id,
                            BroadcastAttempt.status == "pending",
                            or_(
                                BroadcastAttempt.next_attempt_at.is_(None),
                                BroadcastAttempt.next_attempt_at
                                <= pending_reference_now,
                            ),
                        )
                    )
                ).scalar_one()
                or 0
            )

            provider_constrained_pending = int(
                (
                    await db.execute(
                        select(func.count(BroadcastAttempt.id)).where(
                            BroadcastAttempt.user_id == str(user_id),
                            BroadcastAttempt.campaign_id == campaign_id,
                            BroadcastAttempt.status == "pending",
                            BroadcastAttempt.terminal_reason_code
                            == "retriable-rate-limit",
                        )
                    )
                ).scalar_one()
                or 0
            )

        summary = {"sent": 0, "failed": 0, "pending": 0, "inFlight": 0}
        for status, count in rows:
            if status == "sent":
                summary["sent"] = count
            elif status == "failed-terminal":
                summary["failed"] = count
            elif status == "pending":
                summary["pending"] = count
            elif status == "in-flight":
                summary["inFlight"] = count

        next_due_in_ms = 0
        if min_pending_next_attempt is not None:
            delta = (min_pending_next_attempt - utcnow()).total_seconds() * 1000
            next_due_in_ms = max(0, int(delta))
        summary["nextDueInMs"] = next_due_in_ms
        summary["readyPendingCount"] = ready_pending_count
        summary["providerConstrainedDelay"] = provider_constrained_pending > 0

        return BroadcastExecutionResult(
            success=summary["failed"] == 0
            and summary["pending"] == 0
            and summary["inFlight"] == 0,
            count=summary["sent"],
            errors=[],
            summary=summary,
        )
