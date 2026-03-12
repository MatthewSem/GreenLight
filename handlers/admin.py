"""Обработчики для админа: broadcast, set_role. Рассылка не добавляется в тикеты/диалоги."""
import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timedelta, timezone

from constants import ADMIN_COMMANDS_HELP
from keyboards import broadcast_confirm_kb
from config import config

from zoneinfo import ZoneInfo

from services.db.tickets import get_tickets_by_status, get_all_users_with_start, set_role
from services.db.users import get_user_role, get_users_by_type

logger = logging.getLogger(__name__)
router = Router(name="admin")

# Таймзона из конфига
TZ = ZoneInfo(config.timezone)

def now_local():
    """Текущее время в заданной таймзоне."""
    return datetime.now(tz=TZ)

def start_of_day_local(dt: datetime):
    """Начало дня в заданной таймзоне."""
    return datetime(dt.year, dt.month, dt.day, tzinfo=TZ)

# Ожидание контента: {admin_tg_id: (content_type, text, file_id)}
broadcast_content: dict[int, tuple[str, str, str | None]] = {}
# Флаг ожидания контента
broadcast_awaiting: set[int] = set()
# Типы рассылки: all, new, existing, lead
BROADCAST_TARGETS = ["all", "new", "existing", "lead"]
# Словарь для хранения выбранного типа рассылки: {admin_tg_id: target_type}
broadcast_targets: dict[int, str] = {}

RATE_LIMIT = 25


def _is_admin(tg_id: int, role: str | None) -> bool:
    return role == "admin" or (config.admin_ids and tg_id in config.admin_ids)

@router.message(F.chat.type == "private", F.text.startswith("/tickets"))
async def cmd_tickets(message: Message):
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])

    if not _is_admin(tg_id, role):
        await message.answer("⛔ Доступно только администратору.")
        return

    parts = message.text.split()
    if len(parts) != 2 or parts[1].lower() not in ("open", "waiting"):
        await message.answer(
            "Использование:\n"
            "/tickets open\n"
            "/tickets waiting"
        )
        return

    status = parts[1].upper()
    tickets = await get_tickets_by_status(status)

    if not tickets:
        await message.answer(f"📭 Нет тикетов со статусом {status}")
        return

    lines: list[str] = []

    for t in tickets:
        lines.append(f"🎫 <b>Ticket#{t['ticket_id']}</b> | <b>{t['status']}</b>")

        client_username = (
            f"@{t['client_username']}"
            if t["client_username"]
            else "—"
        )
        lines.append(f"Клиент: {client_username} ({t['client_user_id']})")

        if status == "WAITING":
            support_username = (
                f"@{t['support_username']}"
                if t["support_username"]
                else "—"
            )
            lines.append(
                f"Support: {support_username} ({t['assigned_to_support_id']})"
            )

        lines.append("")

    await message.answer("\n".join(lines))

@router.message(F.chat.type == "private", F.text == "/help")
async def cmd_help(message: Message):
    """Список команд: для админа — полный с описанием, для остальных — кратко."""
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])

    if _is_admin(tg_id, role):
        await message.answer(ADMIN_COMMANDS_HELP)
    elif role == "support":
        await message.answer(
            """Доступные команды:
/start — Начать диалог с поддержкой
            
/my_tickets - Просмотреть активные тикеты
/transfer_tickets user_name - Передать все свои тикеты другому  
            
/statistik - Статистика.
/stats 01.02.2026 10.02.2026 — Статистика за период\n"""
        )
    else:
        await message.answer(
            "Доступные команды:\n"
            "/start — Начать диалог с поддержкой"
        )


@router.message(F.chat.type == "private", F.text.startswith("/broadcast"))
async def cmd_broadcast(message: Message):
    """Команда /broadcast — только для ADMIN."""
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])

    if not _is_admin(tg_id, role):
        await message.answer("Доступ запрещён.")
        return

    parts = message.text.split(maxsplit=1)
    target_type = parts[1].lower() if len(parts) > 1 else "all"

    if target_type not in BROADCAST_TARGETS:
        await message.answer(
            f"Неверный вариант. Выберите один из: {', '.join(BROADCAST_TARGETS)}\n"
            "Пример: /broadcast all"
        )
        return

    broadcast_content.pop(tg_id, None)
    broadcast_awaiting.add(tg_id)
    broadcast_targets[tg_id] = target_type

    await message.answer(
        f"Выбран тип рассылки: {target_type.upper()}\n"
        "Отправьте текст или файл для рассылки.\n"
        "Для отмены отправьте /cancel"
    )


@router.message(F.chat.type == "private", F.text == "/cancel")
async def cmd_cancel(message: Message):
    """Отмена broadcast."""
    tg_id = message.from_user.id
    broadcast_awaiting.discard(tg_id)
    broadcast_content.pop(tg_id, None)
    await message.answer("Рассылка отменена.")


@router.message(F.chat.type == "private", lambda m: m.from_user and m.from_user.id in broadcast_awaiting)
async def broadcast_receive_content(message: Message):
    """Получение контента для рассылки."""
    tg_id = message.from_user.id
    broadcast_awaiting.discard(tg_id)

    content_type = "text"
    text = message.text or message.caption or ""
    file_id = None

    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        content_type = "audio"
        file_id = message.audio.file_id

    broadcast_content[tg_id] = (content_type, text, file_id)

    preview = text[:300] + "..." if len(text) > 300 else text
    await message.answer(
        f"Предпросмотр:\n{content_type}\n{preview}\n\nПодтвердите рассылку кнопкой:",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "broadcast:confirm")
async def broadcast_confirm_cb(cb: CallbackQuery):
    """Подтверждение рассылки по кнопке."""
    tg_id = cb.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])
    if not _is_admin(tg_id, role):
        await cb.answer("Доступ запрещён", show_alert=True)
        return

    content = broadcast_content.pop(tg_id, None)
    if not content:
        await cb.answer("Контент не найден. Начните заново с /broadcast", show_alert=True)
        return

    await cb.answer("Рассылка запущена")
    await _do_broadcast(cb.message.bot, tg_id, content)


@router.callback_query(F.data == "broadcast:cancel")
async def broadcast_cancel_cb(cb: CallbackQuery):
    """Отмена рассылки по кнопке."""
    tg_id = cb.from_user.id
    broadcast_awaiting.discard(tg_id)
    broadcast_content.pop(tg_id, None)
    await cb.answer("Рассылка отменена")
    await cb.message.edit_reply_markup(reply_markup=None)


async def _do_broadcast(bot, admin_tg_id: int, content: tuple):
    """Выполнить рассылку всем пользователям с /start. Сообщения не пишутся в тикеты."""
    content_type, text, file_id = content

    target_type = broadcast_targets.get(admin_tg_id, "all")

    if target_type == "all":
        user_ids = await get_all_users_with_start()
    else:
        user_ids = await get_users_by_type(target_type.upper())  # NEW, EXISTING, LEAD


    if not user_ids:
        await bot.send_message(
            admin_tg_id,
            "Нет пользователей для рассылки (никто не делал /start в боте).",
        )
        return

    logger.info("Broadcast: отправка %s получателям: %s", content_type, len(user_ids))
    success = 0
    failed = 0
    batch_size = RATE_LIMIT
    delay = 1.0

    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i : i + batch_size]
        for uid in batch:
            try:
                if content_type == "photo":
                    await bot.send_photo(uid, file_id, caption=text or None)
                elif content_type == "document":
                    await bot.send_document(uid, file_id, caption=text or None)
                elif content_type == "video":
                    await bot.send_video(uid, file_id, caption=text or None)
                elif content_type == "voice":
                    await bot.send_voice(uid, file_id, caption=text or None)
                elif content_type == "audio":
                    await bot.send_audio(uid, file_id, caption=text or None)
                else:
                    await bot.send_message(uid, text or "(пусто)")
                success += 1
            except Exception as e:
                logger.warning("Broadcast не доставлен uid=%s: %s", uid, e)
                failed += 1
        await asyncio.sleep(delay)

    report = f"Рассылка завершена.\nДоставлено: {success}\nНе доставлено: {failed}"
    await bot.send_message(admin_tg_id, report)


@router.message(F.chat.type == "private", F.text.startswith("/set_role"))
async def cmd_set_role(message: Message):
    """Команда /set_role <tg_id> <role> — только для ADMIN."""
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])

    if not _is_admin(tg_id, role):
        await message.answer("Доступ запрещён.")
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /set_role <tg_id> <client|support|admin>")
        return

    try:
        target_tg_id = int(parts[1])
    except ValueError:
        await message.answer("tg_id должен быть числом.")
        return

    new_role = parts[2].lower()
    if new_role not in ("client", "support", "admin"):
        await message.answer("Роль: client, support или admin.")
        return

    await set_role(target_tg_id, new_role)
    await message.answer(f"Роль для {target_tg_id} установлена: {new_role}")
