import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, or_, select

from app.config import settings
from app.db import db_session
from app.models import AllowedUser, SentMessage
from app.services.access_service import AccessService
from app.services.broadcast_queue_service import BroadcastQueueService
from app.services.group_service import GroupService
from app.services.scheduler_service import SchedulerService
from app.services.session_service import SessionService

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from app.services.userbot_service import UserbotService


logging.basicConfig(level=logging.INFO, format="[bot] %(asctime)s %(levelname)s %(message)s", force=True)
logger = logging.getLogger("bot_runner")
logging.getLogger("aiogram").setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.WARNING)


class UserState(str, Enum):
    IDLE = "IDLE"
    WAITING_PHONE = "WAITING_PHONE"
    WAITING_CODE = "WAITING_CODE"
    WAITING_PASSWORD = "WAITING_PASSWORD"
    WAITING_BROADCAST_MSG = "WAITING_BROADCAST_MSG"
    WAITING_ADMIN_ANNOUNCE = "WAITING_ADMIN_ANNOUNCE"
    WAITING_INTERVAL = "WAITING_INTERVAL"


access_service = AccessService()
group_service = GroupService()
session_service = SessionService()
userbot_service = UserbotService()
queue_service = BroadcastQueueService()
scheduler_service = SchedulerService(queue_service)

user_states: dict[int, UserState] = {}
temp_phone: dict[int, str] = {}
broadcast_message_text: dict[int, str] = {}


def is_super_admin(username: str | None) -> bool:
    return access_service.normalize_username(username) in access_service.super_admins


def dedupe_remote_groups(groups: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    result: list[dict] = []
    for group in groups:
        gid = str(group.get("id", "")).strip()
        title_key = " ".join(str(group.get("title", "")).strip().lower().split())
        if not gid or gid in seen_ids or title_key in seen_titles:
            continue
        seen_ids.add(gid)
        seen_titles.add(title_key)
        result.append(group)
    return sorted(result, key=lambda item: str(item.get("title", "")))


def main_menu(has_session: bool, is_admin_user: bool, is_active: bool = False) -> InlineKeyboardMarkup:
    if is_admin_user:
        rows = [
            [
                InlineKeyboardButton(text="🕒 So'rovlar", callback_data="admin_panel_requested"),
                InlineKeyboardButton(text="✅ Ulangan", callback_data="admin_panel_confirmed"),
            ],
            [InlineKeyboardButton(text="👥 Barcha foydalanuvchilar", callback_data="admin_panel_all")],
            [InlineKeyboardButton(text="📣 Barchaga xabar yuborish", callback_data="admin_announce")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if not has_session:
        rows = [
            [InlineKeyboardButton(text="📱 Hisobga kirish (Login)", callback_data="login")],
            [InlineKeyboardButton(text="📚 To'liq ma'lumot", callback_data="full_manual")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    rows = [
        [
            InlineKeyboardButton(
                text=("⏸ Auto-xabarni to'xtatish" if is_active else "▶️ Auto-xabarni boshlash"),
                callback_data=("stop_broadcast" if is_active else "start_broadcast"),
            )
        ],
        [InlineKeyboardButton(text="👥 Guruhlar", callback_data="select_groups"), InlineKeyboardButton(text="📮 Xabar", callback_data="send_message")],
        [InlineKeyboardButton(text="📊 Tarix", callback_data="sent_messages"), InlineKeyboardButton(text="🔄 Yangilash", callback_data="restart_bot")],
        [InlineKeyboardButton(text="📚 To'liq ma'lumot", callback_data="full_manual")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interval_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="3 daqiqa ⏱️", callback_data="set_interval_3"),
                InlineKeyboardButton(text="5 daqiqa ⏱️", callback_data="set_interval_5"),
            ],
            [
                InlineKeyboardButton(text="10 daqiqa ⏱️", callback_data="set_interval_10"),
                InlineKeyboardButton(text="30 daqiqa ⏱️", callback_data="set_interval_30"),
            ],
            [InlineKeyboardButton(text="Boshqa... ⚙️", callback_data="set_interval_custom")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_broadcast")],
        ]
    )


async def show_menu(message: Message, notice: str | None = None):
    has = await session_service.has_session(message.from_user.id)
    admin = is_super_admin(message.from_user.username)
    menu_is_active = False
    if admin:
        now = datetime.utcnow()
        async with db_session() as db:
            total = (await db.execute(select(func.count(AllowedUser.id)))).scalar() or 0
            requested = (await db.execute(select(func.count(AllowedUser.id)).where(AllowedUser.expires_at <= now))).scalar() or 0
            confirmed = (
                await db.execute(
                    select(func.count(AllowedUser.id)).where(or_(AllowedUser.expires_at.is_(None), AllowedUser.expires_at > now))
                )
            ).scalar() or 0
        text = (
            "👑 Admin Panel\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"🕒 So'rovlar: {requested}\n"
            f"✅ Ulangan: {confirmed}\n\n"
            "Kerakli bo'limni tanlang:"
        )
    else:
        text = "👋 Xush kelibsiz!\n\n"
        text += f"🔌 Holat: {'✅ Ulangan' if has else '❌ Ulanmagan'}\n"
        if not has:
            text += "\nBoshlash uchun:\n1) Login qiling\n2) Guruhlarni tanlang\n3) Xabar kiriting va interval tanlang"
        else:
            cfg = await scheduler_service.get_config(str(message.from_user.id))
            active_groups = await group_service.get_groups(str(message.from_user.id), active_only=True)
            is_active = bool(cfg and cfg.is_active)
            menu_is_active = is_active
            interval_min = int(cfg.interval // 60) if cfg and cfg.interval else None
            has_message = bool(cfg and cfg.message)
            text += (
                f"👥 Faol guruhlar: {len(active_groups)}\n"
                f"📡 Auto-xabar: {'🟢 Yoniq' if is_active else '⚪️ Ochiq emas'}\n"
                f"⏱ Interval: {f'{interval_min} daqiqa' if interval_min else 'Belgilanmagan'}\n"
                f"📝 Matn: {'✅ Mavjud' if has_message else '❌ Kiritilmagan'}\n\n"
                "Quyidan kerakli bo'limni tanlang:"
            )
            if active_groups:
                preview = ", ".join(g.title for g in active_groups[:3])
                more = f" +{len(active_groups) - 3}" if len(active_groups) > 3 else ""
                text += f"\n\nUlangan guruhlar: {preview}{more}"
    if notice:
        text = f"{notice}\n\n{text}"
    await message.answer(text, reply_markup=main_menu(has, admin, menu_is_active))


async def show_menu_callback(callback: CallbackQuery, notice: str | None = None):
    has = await session_service.has_session(callback.from_user.id)
    admin = is_super_admin(callback.from_user.username)
    menu_is_active = False
    if admin:
        now = datetime.utcnow()
        async with db_session() as db:
            total = (await db.execute(select(func.count(AllowedUser.id)))).scalar() or 0
            requested = (await db.execute(select(func.count(AllowedUser.id)).where(AllowedUser.expires_at <= now))).scalar() or 0
            confirmed = (
                await db.execute(
                    select(func.count(AllowedUser.id)).where(or_(AllowedUser.expires_at.is_(None), AllowedUser.expires_at > now))
                )
            ).scalar() or 0
        text = (
            "👑 Admin Panel\n\n"
            f"👥 Jami foydalanuvchi: {total}\n"
            f"🕒 So'rovlar: {requested}\n"
            f"✅ Ulangan: {confirmed}\n\n"
            "Kerakli bo'limni tanlang:"
        )
    else:
        text = "👋 Xush kelibsiz!\n\n"
        text += f"🔌 Holat: {'✅ Ulangan' if has else '❌ Ulanmagan'}\n"
        if not has:
            text += "\nBoshlash uchun:\n1) Login qiling\n2) Guruhlarni tanlang\n3) Xabar kiriting va interval tanlang"
        else:
            cfg = await scheduler_service.get_config(str(callback.from_user.id))
            active_groups = await group_service.get_groups(str(callback.from_user.id), active_only=True)
            is_active = bool(cfg and cfg.is_active)
            menu_is_active = is_active
            interval_min = int(cfg.interval // 60) if cfg and cfg.interval else None
            has_message = bool(cfg and cfg.message)
            text += (
                f"👥 Faol guruhlar: {len(active_groups)}\n"
                f"📡 Auto-xabar: {'🟢 Yoniq' if is_active else '⚪️ Ochiq emas'}\n"
                f"⏱ Interval: {f'{interval_min} daqiqa' if interval_min else 'Belgilanmagan'}\n"
                f"📝 Matn: {'✅ Mavjud' if has_message else '❌ Kiritilmagan'}\n\n"
                "Quyidan kerakli bo'limni tanlang:"
            )
            if active_groups:
                preview = ", ".join(g.title for g in active_groups[:3])
                more = f" +{len(active_groups) - 3}" if len(active_groups) > 3 else ""
                text += f"\n\nUlangan guruhlar: {preview}{more}"
    if notice:
        text = f"{notice}\n\n{text}"
    markup = main_menu(has, admin, menu_is_active)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)


async def ensure_logged_in(callback: CallbackQuery) -> bool:
    ok, reason = await access_service.check_access(
        tg_user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
    )
    if not ok:
        await callback.answer(reason or "⛔ Ruxsat yo'q", show_alert=True)
        return False

    if await session_service.has_session(callback.from_user.id):
        return True
    await callback.answer("⛔ Ruxsat yo'q. Avval login qiling.", show_alert=True)
    await show_menu_callback(callback, "⛔ Ruxsat yo'q. Avval login qiling.")
    return False


async def get_last_saved_message(user_id: int) -> str | None:
    async with db_session() as db:
        row = (
            await db.execute(
                select(SentMessage)
                .where(SentMessage.user_id == str(user_id))
                .order_by(SentMessage.created_at.desc(), SentMessage.id.desc())
                .limit(1)
            )
        ).scalars().first()
    return row.text if row and row.text else None


async def save_message_history_if_new(user_id: int, text: str) -> None:
    content = (text or "").strip()
    if not content:
        return
    last = await get_last_saved_message(user_id)
    if last == content:
        return
    async with db_session() as db:
        db.add(SentMessage(text=content, sent_count=0, user_id=str(user_id)))


async def show_group_selection(message: Message, is_edit: bool = False):
    groups = await group_service.get_groups(str(message.from_user.id), active_only=False)
    text = "Guruhlarni tanlang:\n\n"
    text += f"✅ Jami qo'shilgan guruhlar: {len(groups)} ta\n\n"
    if groups:
        preview_lines = [f"• {g.title}" for g in groups[:12]]
        text += "Ulangan guruhlar:\n" + "\n".join(preview_lines)
        if len(groups) > 12:
            text += f"\n... va yana {len(groups) - 12} ta"
        text += "\n\n"
    text += "⚠️ Eslatma: Guruhni ro'yxatdan o'chirish uchun ustiga bosing (❌)"
    rows = []
    row = []
    for group in groups:
        title = group.title
        if len(title) > 15:
            title = title[:15] + "..."
        row.append(InlineKeyboardButton(text=f"❌ {title}", callback_data=f"toggle_group_{group.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if groups:
        rows.append([InlineKeyboardButton(text="Hammasini o'chirish 🗑", callback_data="deselect_all_groups")])
    rows.append([InlineKeyboardButton(text="Guruh qo'shish (Import) ➕", callback_data="add_group")])
    rows.append([InlineKeyboardButton(text="Ortga", callback_data="back_to_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if is_edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)


async def render_admin_panel(
    message: Message,
    filter_name: str = "all",
    page: int = 0,
    is_edit: bool = False,
    actor_username: str | None = None,
):
    username = actor_username if actor_username is not None else message.from_user.username
    if not is_super_admin(username):
        await message.answer("Ruxsat yo'q ⛔️")
        return

    per_page = 10
    now = datetime.utcnow()

    async with db_session() as db:
        total = (await db.execute(select(func.count(AllowedUser.id)))).scalar() or 0
        requested_q = select(func.count(AllowedUser.id)).where(AllowedUser.expires_at <= now)
        confirmed_q = select(func.count(AllowedUser.id)).where(
            or_(AllowedUser.expires_at.is_(None), AllowedUser.expires_at > now)
        )
        requested = (await db.execute(requested_q)).scalar() or 0
        confirmed = (await db.execute(confirmed_q)).scalar() or 0

        where_clause = None
        if filter_name == "requested":
            where_clause = AllowedUser.expires_at <= now
            total_for_filter = requested
        elif filter_name == "confirmed":
            where_clause = or_(AllowedUser.expires_at.is_(None), AllowedUser.expires_at > now)
            total_for_filter = confirmed
        else:
            total_for_filter = total

        query = select(AllowedUser)
        if where_clause is not None:
            query = query.where(where_clause)
        if filter_name == "requested":
            query = query.order_by(AllowedUser.expires_at.desc(), AllowedUser.created_at.desc())
        else:
            query = query.order_by(AllowedUser.created_at.desc())
        query = query.offset(page * per_page).limit(per_page)
        users = (await db.execute(query)).scalars().all()

    total_pages = max(1, (total_for_filter + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    filter_title = {
        "all": "👥 Barchasi",
        "requested": "🕒 So'rovlar",
        "confirmed": "✅ Ulangan",
    }.get(filter_name, "👥 Barchasi")

    title = (
        "👑 Admin Dashboard\n\n"
        "📊 Statistika\n"
        f"• Jami foydalanuvchi: {total}\n"
        f"• So'rovlar: {requested}\n"
        f"• Ulangan: {confirmed}\n\n"
        f"🔎 Filter: {filter_title}\n"
        f"📄 Sahifa: {page + 1}/{total_pages}"
    )

    rows = []
    user_row = []
    for u in users:
        raw_name = u.username or u.first_name or u.id
        name = str(raw_name)
        if len(name) > 16:
            name = name[:16] + "..."
        is_active_user = bool(u.expires_at is None or u.expires_at > now)
        icon = "🟢" if is_active_user else "🟠"
        user_row.append(InlineKeyboardButton(text=f"{icon} {name}", callback_data=f"admin_user_{u.id}"))
        if len(user_row) == 2:
            rows.append(user_row)
            user_row = []
    if user_row:
        rows.append(user_row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"admin_panel_{filter_name}_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"admin_panel_{filter_name}_page_{page + 1}"))
    if nav:
        rows.append(nav)

    rows += [
        [
            InlineKeyboardButton(text="👥 Barchasi", callback_data="admin_panel_all"),
            InlineKeyboardButton(text="✅ Ulangan", callback_data="admin_panel_confirmed"),
            InlineKeyboardButton(text="🕒 So'rovlar", callback_data="admin_panel_requested"),
        ],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"admin_panel_{filter_name}_page_{page}")],
        [InlineKeyboardButton(text="📣 Barchaga xabar", callback_data="admin_announce")],
        [InlineKeyboardButton(text="⬅️ Asosiy Menyu", callback_data="back_to_menu")],
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if is_edit:
        try:
            await message.edit_text(title, reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(title, reply_markup=markup)


async def start_handler(message: Message):
    logger.info("Received /start or /menu from user_id=%s username=%s", message.from_user.id, message.from_user.username)
    ok, reason = await access_service.check_access(
        tg_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if not ok:
        await message.answer(reason)
        return
    await show_menu(message)


async def cancel_handler(message: Message):
    user_states[message.from_user.id] = UserState.IDLE
    await message.answer("Amalyot bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await show_menu(message)


async def id_handler(message: Message):
    await message.answer(f"Sizning ID: {message.from_user.id}")


async def info_handler(message: Message):
    if is_super_admin(message.from_user.username):
        async with db_session() as db:
            count = (await db.execute(select(func.count(AllowedUser.id)))).scalar() or 0
        await message.answer(f"👑 Siz Super Adminsiz.\n👥 Jami foydalanuvchilar: {count}")
        return

    async with db_session() as db:
        user = await db.get(AllowedUser, str(message.from_user.id))

    if not user:
        await message.answer("Siz ro'yxatda topilmadingiz")
        return

    if user.expires_at:
        await message.answer(f"👤 Sizning holatingiz:\n📅 Tugash vaqti: {user.expires_at.strftime('%Y-%m-%d')}")
    else:
        await message.answer("👤 Sizning holatingiz:\n♾ Doimiy")


async def adduser_handler(message: Message):
    if not is_super_admin(message.from_user.username):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /adduser <telegram_id> <days>")
        return
    target_id = parts[1]
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
    expires = datetime.utcnow() + timedelta(days=days)

    async with db_session() as db:
        row = await db.get(AllowedUser, target_id)
        if row:
            row.expires_at = expires
            row.username = row.username or "User"
        else:
            db.add(AllowedUser(id=target_id, username="User", expires_at=expires))

    await message.answer(f"✅ Foydalanuvchi qo'shildi!\nID: {target_id}\nMuddat: {days} kun")


async def ban_handler(message: Message):
    if not is_super_admin(message.from_user.username):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /ban <id>")
        return
    target_id = parts[1]
    async with db_session() as db:
        row = await db.get(AllowedUser, target_id)
        if row:
            await db.delete(row)
    await message.answer(f"🚫 Foydalanuvchi bloklandi: {target_id}")


async def on_login(callback: CallbackQuery):
    if await session_service.has_session(callback.from_user.id):
        await show_menu_callback(callback)
        await callback.answer("Siz allaqachon tizimga kirgansiz ✅")
        return
    user_states[callback.from_user.id] = UserState.WAITING_PHONE
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(
        "Iltimos, telefon raqamingizni xalqaro formatda yuboring.\nMasalan: +998901234567\nYoki quyidagi tugmani bosib raqamingizni yuboring.",
        reply_markup=kb,
    )
    await callback.answer()


async def on_select_groups(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    await show_group_selection(callback.message, is_edit=True)
    await callback.answer()


async def on_add_group(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    page = 0
    if callback.data.startswith("add_group_page_"):
        page = max(0, int(callback.data.removeprefix("add_group_page_")))

    await render_add_group_page(callback.message, callback.from_user.id, page, is_edit=True)
    await callback.answer()


async def render_add_group_page(message: Message, user_id: int, page: int, is_edit: bool = False):
    remote = await userbot_service.get_remote_groups(user_id)
    db_groups = await group_service.get_groups(str(user_id), active_only=False)
    existing = {g.id for g in db_groups}
    options = dedupe_remote_groups(remote)

    if not options:
        await message.answer("Telegram profilingizda hech qanday guruh topilmadi 🤷‍♂️")
        return

    per_page = 10
    total_pages = max(1, (len(options) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    batch = options[page * per_page : (page + 1) * per_page]

    def clip(value: str, limit: int = 20) -> str:
        return value if len(value) <= limit else value[:limit] + "..."

    rows = []
    row = []
    for g in batch:
        gid = str(g.get("id"))
        icon = "✅" if gid in existing else "❌"
        row.append(InlineKeyboardButton(text=f"{icon} {clip(g['title'])}", callback_data=f"import_group_{gid}_{page}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"add_group_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"add_group_page_{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="select_groups")])
    selected_count = len(existing.intersection({str(g.get("id")) for g in options}))
    text = (
        "📋 Guruh qo'shish:\n"
        "Profilingizdagi guruhlarni tanlang (✅ tanlangan, ❌ tanlanmagan):\n"
        f"(Sahifa {page + 1}/{total_pages} | Tanlangan: {selected_count}/{len(options)})"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if is_edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=markup)


async def on_import_groups_cmd(message: Message):
    groups = await userbot_service.get_remote_groups(message.from_user.id)
    added = 0
    for g in groups:
        await group_service.add_group(
            str(message.from_user.id),
            str(g["id"]),
            g["title"],
            g.get("type", "chat"),
            g.get("access_hash"),
        )
        added += 1
    await message.answer(f"Import tugadi: {added} ta")


async def on_import_group(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    payload = callback.data.removeprefix("import_group_")
    if "_" in payload:
        group_id, page = payload.rsplit("_", 1)
    else:
        group_id, page = payload, "0"
    remote = dedupe_remote_groups(await userbot_service.get_remote_groups(callback.from_user.id))
    target = next((g for g in remote if g["id"] == group_id), None)
    if not target:
        await callback.answer("Xatolik: Guruh topilmadi")
        return

    db_groups = await group_service.get_groups(str(callback.from_user.id), active_only=False)
    exists = next((g for g in db_groups if g.id == str(target["id"])), None)
    if exists:
        await group_service.remove_group(str(callback.from_user.id), str(target["id"]))
        await callback.answer(f"O'chirildi: {target['title']} ❌")
    else:
        await group_service.add_group(
            str(callback.from_user.id),
            str(target["id"]),
            target["title"],
            target.get("type", "chat"),
            target.get("access_hash"),
        )
        await callback.answer(f"Qo'shildi: {target['title']} ✅")

    await render_add_group_page(callback.message, callback.from_user.id, int(page), is_edit=True)


async def on_toggle_group(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    group_id = callback.data.removeprefix("toggle_group_")
    await group_service.remove_group(str(callback.from_user.id), group_id)
    await callback.answer("Ro'yxatdan o'chirildi 🗑")
    await show_group_selection(callback.message, is_edit=True)


async def on_deselect_all_groups(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    groups = await group_service.get_groups(str(callback.from_user.id), active_only=False)
    for g in groups:
        await group_service.remove_group(str(callback.from_user.id), g.id)
    await callback.answer("Barchasi o'chirildi 🗑")
    await show_group_selection(callback.message, is_edit=True)


async def on_send_message_mode(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    user_states[callback.from_user.id] = UserState.WAITING_BROADCAST_MSG
    last = await get_last_saved_message(callback.from_user.id)
    if last:
        preview = (last[:80] + "...") if len(last) > 80 else last
        await callback.message.answer(f"Oxirgi saqlangan xabar:\n\n{preview}\n\nYangi xabar yuboring:")
    else:
        await callback.message.answer("Xabar matnini yuboring yoki rasm/video tashlang:")
    await callback.answer()


async def on_start_broadcast(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    cfg = await scheduler_service.get_config(str(callback.from_user.id))
    if not cfg or not cfg.interval:
        await callback.message.answer(
            "Auto-Broadcastni yoqish uchun avval intervalni sozlang (Xabar yuborish -> interval tanlash)."
        )
        await show_menu_callback(callback)
        await callback.answer()
        return

    message_text = (cfg.message or "").strip()
    if not message_text:
        message_text = (await get_last_saved_message(callback.from_user.id) or "").strip()
        if message_text:
            await scheduler_service.set_config(str(callback.from_user.id), message=message_text)

    if not message_text:
        await callback.message.answer(
            "Auto-Broadcastni yoqish uchun avval xabar va intervalni sozlang (Xabar yuborish -> interval tanlash)."
        )
        await show_menu_callback(callback)
        await callback.answer()
        return
    await scheduler_service.set_config(str(callback.from_user.id), is_active=True)
    await show_menu_callback(callback, f"✅ Auto-Broadcast ishga tushirildi!\n⏱ Interval: {int(cfg.interval // 60)} daqiqa")
    await callback.answer()


async def on_stop_broadcast(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    await scheduler_service.set_config(str(callback.from_user.id), is_active=False)
    await show_menu_callback(callback, "🛑 Auto-Broadcast to'xtatildi.")
    await callback.answer()


async def on_back_to_menu(callback: CallbackQuery):
    await show_menu_callback(callback)
    await callback.answer()


async def on_about_bot(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Matnli yo'riqnoma", callback_data="about_bot_text")],
            [InlineKeyboardButton(text="🎥 Video Yo‘riqnoma", callback_data="about_bot_video")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")],
        ]
    )
    await callback.message.answer("📚 Bot haqida\nQulay formatni tanlang:", reply_markup=kb)
    await callback.answer()


async def on_full_manual(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Matnli yo'riqnoma", callback_data="about_bot_text")],
            [InlineKeyboardButton(text="🎥 Video yo‘riqnoma", callback_data="about_bot_video")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_menu")],
        ]
    )
    await callback.message.answer("📚 To'liq ma'lumot\nQulay formatni tanlang:", reply_markup=kb)
    await callback.answer()


async def on_search_messages(callback: CallbackQuery):
    await callback.message.answer("Qidiruv funksiyasi tez orada qo'shiladi 🔍")
    await callback.answer()


async def on_restart_bot(callback: CallbackQuery):
    await callback.answer("Qayta yuklanmoqda...")
    await show_menu_callback(callback)


async def on_about_bot_text(callback: CallbackQuery):
    text = (
        "✨ Bot qanday ishlaydi\n\n"
        "1. Login qiling\n"
        "2. Xabar matnini kiriting\n"
        "3. Interval tanlang\n"
        "4. Bot avtomatik yuboradi\n\n"
        "Savol bo‘lsa admin bilan bog‘laning."
    )
    await callback.message.answer(text)
    await callback.answer()


async def on_about_bot_video(callback: CallbackQuery):
    video_id = settings.tg_manual_video_id or ""
    if not video_id:
        await callback.message.answer("Video yo'riqnoma hali sozlanmagan.")
    else:
        try:
            await callback.message.answer_video(video_id)
        except Exception:
            await callback.message.answer("Video yuborishda xatolik yuz berdi.")
    await callback.answer()


async def on_sent_messages(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    page = 0
    if callback.data.startswith("sent_messages_page_"):
        page = max(0, int(callback.data.removeprefix("sent_messages_page_")))
    per_page = 5

    async with db_session() as db:
        total = (
            await db.execute(select(func.count(SentMessage.id)).where(SentMessage.user_id == str(callback.from_user.id)))
        ).scalar() or 0
        rows = (
            await db.execute(
                select(SentMessage)
                .where(SentMessage.user_id == str(callback.from_user.id))
                .order_by(SentMessage.created_at.desc())
                .offset(page * per_page)
                .limit(per_page)
            )
        ).scalars().all()

    if not rows:
        try:
            await callback.message.edit_text("Tarix bo'sh")
        except Exception:
            await callback.message.answer("Tarix bo'sh")
        await callback.answer()
        return

    total_pages = max(1, (total + per_page - 1) // per_page)
    text = f"📊 Ish tarixi\nJami: {total} ta"
    buttons = []
    for r in rows:
        date_str = r.created_at.strftime("%Y-%m-%d")
        preview = (r.text[:20] + "...") if len(r.text) > 20 else r.text
        buttons.append([InlineKeyboardButton(text=f"📝 {date_str} - {preview}", callback_data=f"history_view_{r.id}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"sent_messages_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"sent_messages_page_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ Asosiy Menyu", callback_data="back_to_menu")])

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


async def on_history_view(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    msg_id = int(callback.data.removeprefix("history_view_"))
    async with db_session() as db:
        row = await db.get(SentMessage, msg_id)
    if not row:
        await callback.answer("Xabar topilmadi")
        return

    text = f"📅 Vaqt: {row.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n📝 Xabar:\n{row.text}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"history_delete_{row.id}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sent_messages")],
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


async def on_history_delete(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    msg_id = int(callback.data.removeprefix("history_delete_"))
    async with db_session() as db:
        row = await db.get(SentMessage, msg_id)
        if row:
            await db.delete(row)
    await callback.answer("O'chirildi 🗑")
    try:
        await callback.message.edit_text(
            "Xabar o'chirildi.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sent_messages")]]
            ),
        )
    except Exception:
        await callback.message.answer("Xabar o'chirildi.")


async def on_set_interval_custom(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    user_states[callback.from_user.id] = UserState.WAITING_INTERVAL
    await callback.message.answer("Iltimos, intervalni daqiqalarda kiriting (masalan: 60):")
    await callback.answer()


async def on_cancel_broadcast(callback: CallbackQuery):
    if not await ensure_logged_in(callback):
        return
    user_states[callback.from_user.id] = UserState.IDLE
    broadcast_message_text.pop(callback.from_user.id, None)
    await callback.message.answer("Xabar yuborish bekor qilindi ❌")
    await show_menu_callback(callback)
    await callback.answer()


async def on_admin_panel(callback: CallbackQuery):
    await render_admin_panel(callback.message, is_edit=True, actor_username=callback.from_user.username)
    await callback.answer()


async def on_admin_filter_panel(callback: CallbackQuery):
    payload = callback.data.removeprefix("admin_panel_")
    filter_name = payload.split("_page_")[0]
    page = 0
    if "_page_" in payload:
        page = int(payload.split("_page_")[1])
    await render_admin_panel(
        callback.message,
        filter_name=filter_name,
        page=page,
        is_edit=True,
        actor_username=callback.from_user.username,
    )
    await callback.answer()


async def on_admin_user(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.username):
        await callback.answer("Ruxsat yo'q ⛔️")
        return
    user_id = callback.data.removeprefix("admin_user_")
    async with db_session() as db:
        row = await db.get(AllowedUser, user_id)
    if not row:
        await callback.answer("User topilmadi")
        return
    status = row.expires_at.strftime("%Y-%m-%d") if row.expires_at else "Doimiy"
    is_active_user = bool(row.expires_at is None or row.expires_at > datetime.utcnow())
    state_text = "🟢 Faol" if is_active_user else "🟠 So'rovda"
    display_name = row.username or row.first_name or row.id
    text = (
        "👤 Foydalanuvchi kartasi\n\n"
        f"• Username: @{display_name}\n"
        f"• ID: {row.id}\n"
        f"• Holat: {state_text}\n"
        f"• Tugash muddati: {status}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ +30 kun", callback_data=f"admin_add_month_{user_id}"),
                InlineKeyboardButton(text="➖ -30 kun", callback_data=f"admin_sub_month_{user_id}"),
            ],
            [InlineKeyboardButton(text="🚫 Block", callback_data=f"admin_block_{user_id}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_panel_all")],
        ]
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


async def adjust_expiry(callback: CallbackQuery, days: int):
    if not is_super_admin(callback.from_user.username):
        await callback.answer("Ruxsat yo'q ⛔️")
        return
    user_id = callback.data.split("_")[-1]
    async with db_session() as db:
        row = await db.get(AllowedUser, user_id)
        if not row:
            await callback.answer("User topilmadi")
            return
        base = row.expires_at if row.expires_at and row.expires_at > datetime.utcnow() else datetime.utcnow()
        row.expires_at = base + timedelta(days=days)
    await callback.answer("Muddat yangilandi")
    await render_admin_panel(callback.message, is_edit=True, actor_username=callback.from_user.username)


async def on_admin_add_month(callback: CallbackQuery):
    await adjust_expiry(callback, 30)


async def on_admin_sub_month(callback: CallbackQuery):
    await adjust_expiry(callback, -30)


async def on_admin_block(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.username):
        await callback.answer("Ruxsat yo'q ⛔️")
        return
    user_id = callback.data.removeprefix("admin_block_")
    async with db_session() as db:
        row = await db.get(AllowedUser, user_id)
        if row:
            await db.delete(row)
    await callback.answer("Foydalanuvchi bloklandi 🚫")
    await render_admin_panel(callback.message, is_edit=True, actor_username=callback.from_user.username)


async def on_admin_announce(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.username):
        await callback.answer("Ruxsat yo'q ⛔️")
        return
    user_states[callback.from_user.id] = UserState.WAITING_ADMIN_ANNOUNCE
    await callback.message.answer("📣 Barchaga yuboriladigan xabarni yozing:")
    await callback.answer()


async def on_contact(message: Message):
    ok, reason = await access_service.check_access(
        tg_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if not ok:
        user_states[message.from_user.id] = UserState.IDLE
        await message.answer(reason or "⛔ Ruxsat yo'q")
        return

    user_id = message.from_user.id
    if user_states.get(user_id) != UserState.WAITING_PHONE:
        return
    phone = message.contact.phone_number
    res = await userbot_service.start_login(user_id, phone)
    logger.info("start_login(contact) result user_id=%s success=%s error=%s", user_id, res.get("success"), res.get("error"))
    if res.get("success"):
        user_states[user_id] = UserState.WAITING_CODE
        temp_phone[user_id] = phone
        await message.answer("Kod yuborildi. Kodni kiriting", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer(f"Xato: {res.get('error')}")


async def on_text(message: Message):
    ok, reason = await access_service.check_access(
        tg_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if not ok:
        user_states[message.from_user.id] = UserState.IDLE
        await message.answer(reason or "⛔ Ruxsat yo'q")
        return

    user_id = message.from_user.id
    text = (message.text or "").strip()
    state = user_states.get(user_id, UserState.IDLE)
    digits_only = "".join(ch for ch in text if ch.isdigit())
    logger.info("Incoming text user_id=%s state=%s text=%s", user_id, state, text)

    async def verify_code_flow() -> None:
        phone = temp_phone.get(user_id)
        if not phone:
            user_states[user_id] = UserState.IDLE
            await message.answer("Session topilmadi. Qaytadan Login bosing.")
            return
        res = await userbot_service.complete_login(user_id, phone, text)
        logger.info(
            "complete_login result user_id=%s success=%s requiresPassword=%s error=%s",
            user_id,
            res.get("success"),
            res.get("requiresPassword"),
            res.get("error"),
        )
        if res.get("success"):
            user_states[user_id] = UserState.IDLE
            temp_phone.pop(user_id, None)
            await show_menu(message, "✅ Login muvaffaqiyatli")
        elif res.get("requiresPassword"):
            user_states[user_id] = UserState.WAITING_PASSWORD
            await message.answer("2FA parol kiriting")
        elif res.get("errorCode") == "PHONE_CODE_EXPIRED":
            user_states[user_id] = UserState.WAITING_PHONE
            await userbot_service.cancel_login(user_id)
            temp_phone.pop(user_id, None)
            await message.answer("Kod eskirgan. Qaytadan Login bosing.")
        else:
            await message.answer(f"Xato: {res.get('error')}")

    if state == UserState.WAITING_PHONE:
        if temp_phone.get(user_id) and 4 <= len(digits_only) <= 8:
            user_states[user_id] = UserState.WAITING_CODE
            await verify_code_flow()
            return

        res = await userbot_service.start_login(user_id, text)
        logger.info("start_login(text) result user_id=%s success=%s error=%s", user_id, res.get("success"), res.get("error"))
        if res.get("success"):
            user_states[user_id] = UserState.WAITING_CODE
            temp_phone[user_id] = text
            await message.answer("Kod yuborildi. Kodni kiriting")
        else:
            await message.answer(f"Xato: {res.get('error')}")
        return

    if state == UserState.WAITING_CODE:
        await verify_code_flow()
        return

    if state == UserState.WAITING_PASSWORD:
        phone = temp_phone.get(user_id)
        if not phone:
            user_states[user_id] = UserState.IDLE
            await message.answer("Session topilmadi")
            return
        res = await userbot_service.complete_2fa(user_id, phone, text)
        if res.get("success"):
            user_states[user_id] = UserState.IDLE
            temp_phone.pop(user_id, None)
            await show_menu(message, "✅ Login + 2FA muvaffaqiyatli")
        else:
            await message.answer(f"Xato: {res.get('error')}")
        return

    if state == UserState.WAITING_BROADCAST_MSG:
        broadcast_message_text[user_id] = text
        await scheduler_service.set_config(str(user_id), message=text)
        await save_message_history_if_new(user_id, text)
        user_states[user_id] = UserState.IDLE
        await message.answer("Xabar tasdiqlandi. Yuborish intervalini tanlang:", reply_markup=interval_menu())
        return

    if state == UserState.WAITING_INTERVAL:
        if not text.isdigit():
            await message.answer("Iltimos, to'g'ri raqam kiriting (kamida 1 daqiqa):")
            return
        minutes = int(text)
        if minutes < 1:
            await message.answer("Iltimos, to'g'ri raqam kiriting (kamida 1 daqiqa):")
            return
        msg = broadcast_message_text.get(user_id)
        if not msg:
            cfg = await scheduler_service.get_config(str(user_id))
            if cfg and cfg.message:
                msg = cfg.message
            else:
                msg = await get_last_saved_message(user_id)
        if not msg:
            user_states[user_id] = UserState.IDLE
            await message.answer("Xabar topilmadi")
            return
        await scheduler_service.set_config(str(user_id), message=msg, interval=minutes * 60, is_active=True)
        await save_message_history_if_new(user_id, msg)
        user_states[user_id] = UserState.IDLE
        await show_menu(message, f"✅ Auto Broadcast ishga tushirildi!\n⏱ Interval: {minutes} daqiqa")
        return

    if state == UserState.WAITING_ADMIN_ANNOUNCE and is_super_admin(message.from_user.username):
        async with db_session() as db:
            users = (
                await db.execute(select(AllowedUser.id).where(or_(AllowedUser.expires_at.is_(None), AllowedUser.expires_at > datetime.utcnow())))
            ).all()

        bot = Bot(token=settings.tg_bot_token)
        sent = 0
        for (uid,) in users:
            try:
                await bot.send_message(chat_id=int(uid), text=text)
                sent += 1
            except Exception:
                continue
        await bot.session.close()
        user_states[user_id] = UserState.IDLE
        await message.answer(f"📣 Xabar yuborildi: {sent} foydalanuvchi")
        return

    if state == UserState.IDLE and 4 <= len(digits_only) <= 8:
        await message.answer("Kodni qabul qilish uchun avval Login jarayonini boshlang: /start -> 📱 Login")


async def on_interval_callback(callback: CallbackQuery):
    minutes = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    msg = broadcast_message_text.get(user_id)
    if not msg:
        cfg = await scheduler_service.get_config(str(user_id))
        if cfg and cfg.message:
            msg = cfg.message
        else:
            msg = await get_last_saved_message(user_id)
    if not msg:
        await callback.message.answer("Xabar topilmadi")
        await callback.answer()
        return
    await scheduler_service.set_config(str(user_id), message=msg, interval=minutes * 60, is_active=True)
    await save_message_history_if_new(user_id, msg)
    user_states[user_id] = UserState.IDLE
    await show_menu_callback(callback, f"✅ Auto Broadcast ishga tushirildi!\n⏱ Interval: {minutes} daqiqa")
    await callback.answer()


async def main():
    logger.info("Starting aiogram bot runner...")
    bot = Bot(token=settings.tg_bot_token)
    dp = Dispatcher()

    dp.message.register(start_handler, Command("start"))
    dp.message.register(start_handler, Command("menu"))
    dp.message.register(cancel_handler, Command("cancel"))
    dp.message.register(adduser_handler, Command("adduser"))
    dp.message.register(ban_handler, Command("ban"))
    dp.message.register(info_handler, Command("info"))
    dp.message.register(id_handler, Command("id"))

    dp.callback_query.register(on_login, F.data == "login")
    dp.callback_query.register(on_select_groups, F.data == "select_groups")
    dp.callback_query.register(on_add_group, F.data == "add_group")
    dp.callback_query.register(on_add_group, F.data.startswith("add_group_page_"))
    dp.callback_query.register(on_import_group, F.data.startswith("import_group_"))
    dp.callback_query.register(on_toggle_group, F.data.startswith("toggle_group_"))
    dp.callback_query.register(on_deselect_all_groups, F.data == "deselect_all_groups")
    dp.callback_query.register(on_send_message_mode, F.data == "send_message")
    dp.callback_query.register(on_search_messages, F.data == "search_messages")
    dp.callback_query.register(on_restart_bot, F.data == "restart_bot")
    dp.callback_query.register(on_full_manual, F.data == "full_manual")
    dp.callback_query.register(on_start_broadcast, F.data == "start_broadcast")
    dp.callback_query.register(on_stop_broadcast, F.data == "stop_broadcast")
    dp.callback_query.register(on_sent_messages, F.data == "sent_messages")
    dp.callback_query.register(on_sent_messages, F.data.startswith("sent_messages_page_"))
    dp.callback_query.register(on_history_view, F.data.startswith("history_view_"))
    dp.callback_query.register(on_history_delete, F.data.startswith("history_delete_"))
    dp.callback_query.register(on_set_interval_custom, F.data == "set_interval_custom")
    dp.callback_query.register(on_cancel_broadcast, F.data == "cancel_broadcast")
    dp.callback_query.register(on_back_to_menu, F.data == "back_to_menu")
    dp.callback_query.register(on_about_bot, F.data == "about_bot")
    dp.callback_query.register(on_about_bot_text, F.data == "about_bot_text")
    dp.callback_query.register(on_about_bot_video, F.data == "about_bot_video")
    dp.callback_query.register(on_admin_panel, F.data == "admin_panel")
    dp.callback_query.register(on_admin_filter_panel, F.data.startswith("admin_panel_"))
    dp.callback_query.register(on_admin_user, F.data.startswith("admin_user_"))
    dp.callback_query.register(on_admin_add_month, F.data.startswith("admin_add_month_"))
    dp.callback_query.register(on_admin_sub_month, F.data.startswith("admin_sub_month_"))
    dp.callback_query.register(on_admin_block, F.data.startswith("admin_block_"))
    dp.callback_query.register(on_admin_announce, F.data == "admin_announce")
    dp.callback_query.register(on_interval_callback, F.data.startswith("set_interval_"))

    dp.message.register(on_import_groups_cmd, Command("import_groups"))
    dp.message.register(on_contact, F.contact)
    dp.message.register(on_text, F.text)

    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
