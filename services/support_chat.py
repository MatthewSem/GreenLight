"""Отправка сообщений в Support Group и Admin Chat."""
import logging
from datetime import timezone, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

from config import config
from keyboards import ticket_kb, ticket_status_kb

from constants import MSG_REPLY_PROMPT
from services.db.tickets import get_ticket, get_client_username, get_ticket_messages
from services.db.users import get_user_client_type

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

def to_msk(dt):
    if not dt:
        return "—"
    return dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M")


def _format_ticket_card(
    ticket_id: int,
    status: str,
    client_tg_id: int,
    username: str,
    client_type_label: str,
    last_message: str,
    taken_str: str = "—",
    created_str: str = "—",
) -> str:
    """Формат по ТЗ: карточка тикета с «Последнее сообщение» и текстом клиента."""
    last = last_message[:200] + ("..." if len(last_message) > 200 else "")
    return f"""🎫 Ticket #{ticket_id} | {status}
Тип: {client_type_label}
Клиент: @{username or '—'} ({client_tg_id})
Создан: {created_str} (MSK)
Взят: {taken_str}
Последнее сообщение:
"{last}\""""


async def send_ticket_to_support_group(
    bot: Bot,
    ticket_id: int,
    client_tg_id: int,
    username: str,
    client_type_label: str,
    last_message: str,
    message_thread_id: int | None = None,
) -> int | None:
    """Отправить карточку тикета в Support Group (или в тему, если передан message_thread_id). Возвращает message_id."""
    ticket = await get_ticket(ticket_id)
    if not ticket:
        return None

    status = ticket["status"]
    created_str = to_msk(ticket.get("created_at"))
    taken_str = to_msk(ticket.get("taken_at"))

    text = _format_ticket_card(
        ticket_id, status, client_tg_id, username, client_type_label, last_message,
        taken_str=taken_str, created_str=created_str,
    )

    if not config.support_group_id:
        logger.warning("SUPPORT_GROUP_ID не задан в .env")
        return None

    is_taken = bool(ticket.get("assigned_to_support_id"))
    status = ticket.get("status") or "OPEN"
    try:
        kwargs = {
            "chat_id": config.support_group_id,
            "text": text,
            "reply_markup": ticket_kb(ticket_id, is_taken=is_taken, status=status),
        }
        if message_thread_id is not None:
            kwargs["message_thread_id"] = message_thread_id
        msg = await bot.send_message(**kwargs)
        return msg.message_id
    except TelegramBadRequest as e:
        logger.error(
            f"Не удалось отправить тикет #{ticket_id} в Support Group: {e}. "
            f"Проверьте SUPPORT_GROUP_ID и убедитесь, что бот добавлен в группу (и включены темы, если используете топики)."
        )
        return None
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при отправке тикета #{ticket_id}: {e}")
        return None


async def send_new_client_message_to_topic(
    bot: Bot,
    ticket_id: int,
    support_thread_id: int,
    text: str = None,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> None:
    """Уведомить тему тикета о новом сообщении от клиента с поддержкой медиа."""
    if not config.support_group_id:
        return

    try:
        caption = f"📩 Новое сообщение от клиента (Ticket #{ticket_id}):\n\"{(text or '')[:500]}{'...' if text and len(text) > 500 else ''}\"" if text else None

        if media_type == "photo":
            await bot.send_photo(
                chat_id=config.support_group_id,
                photo=media_file_id,
                caption=caption,
                message_thread_id=support_thread_id
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=config.support_group_id,
                document=media_file_id,
                caption=caption,
                message_thread_id=support_thread_id
            )
        elif media_type == "video":
            await bot.send_video(
                chat_id=config.support_group_id,
                video=media_file_id,
                caption=caption,
                message_thread_id=support_thread_id
            )
        elif media_type == "voice":
            await bot.send_voice(
                chat_id=config.support_group_id,
                voice=media_file_id,
                caption=caption,
                message_thread_id=support_thread_id
            )
        elif media_type == "audio":
            await bot.send_audio(
                chat_id=config.support_group_id,
                audio=media_file_id,
                caption=caption,
                message_thread_id=support_thread_id
            )
        else:
            # Просто текст
            await bot.send_message(
                chat_id=config.support_group_id,
                text=caption or "(медиа)",
                message_thread_id=support_thread_id
            )
    except (TelegramBadRequest, TelegramAPIError) as e:
        logger.warning(f"Не удалось отправить уведомление в тему тикета #{ticket_id}: {e}")


async def update_ticket_card(
    bot: Bot,
    ticket_id: int,
    last_message: str | None = None,
    client_type_label: str = "🆕 Новый",
) -> None:
    """Обновить карточку тикета в support-чате: редактировать сообщение, поменяв «Последнее сообщение»."""
    if not config.support_group_id or not last_message:
        return
    ticket = await get_ticket(ticket_id)
    if not ticket:
        return
    card_msg_id = ticket.get("ticket_card_message_id")
    if not card_msg_id or ticket.get("support_thread_id"):
        return
    client_tg_id = ticket["client_user_id"]
    username = await get_client_username(client_tg_id) or "—"
    status = ticket.get("status") or "OPEN"
    created_str = to_msk(ticket.get("created_at"))
    taken_str = to_msk(ticket.get("taken_at"))
    label = client_type_label
    text = _format_ticket_card(
        ticket_id, status, client_tg_id, username, label, last_message,
        taken_str=taken_str, created_str=created_str,
    )
    is_taken = bool(ticket.get("assigned_to_support_id"))
    try:
        await bot.edit_message_text(
            chat_id=config.support_group_id,
            message_id=card_msg_id,
            text=text,
            reply_markup=ticket_kb(ticket_id, is_taken=is_taken, status=status),
        )
    except (TelegramBadRequest, TelegramAPIError) as e:
        logger.debug("Не удалось отредактировать карточку тикета %s: %s", ticket_id, e)


async def refresh_ticket_card(bot: Bot, ticket_id: int) -> None:
    """
    Обновить карточку тикета в чате (общий чат или топик): пересобрать текст и кнопки,
    отредактировать сообщение. Вызывать после смены статуса и т.п.
    """
    if not config.support_group_id:
        return
    ticket = await get_ticket(ticket_id)
    if not ticket:
        return
    msg_id = None
    thread_id = ticket.get("support_thread_id")
    if thread_id and ticket.get("ticket_topic_card_message_id"):
        msg_id = ticket["ticket_topic_card_message_id"]
    elif ticket.get("ticket_card_message_id"):
        msg_id = ticket["ticket_card_message_id"]
        thread_id = None
    if not msg_id:
        return

    client_tg_id = ticket["client_user_id"]
    ct = await get_user_client_type(client_tg_id)
    client_type_label = "🆕 Новый" if ct == "new" else "👤 Действующий"
    username = await get_client_username(client_tg_id) or "—"
    status = ticket.get("status") or "OPEN"
    created_str = to_msk(ticket.get("created_at"))
    taken_str = to_msk(ticket.get("taken_at"))
    last_msg = "(нет сообщений)"
    msgs = await get_ticket_messages(ticket_id, limit=1)
    if msgs:
        last_msg = msgs[-1].get("text") or "(медиа)"

    text = _format_ticket_card(
        ticket_id, status, client_tg_id, username, client_type_label, last_msg,
        taken_str=taken_str, created_str=created_str,
    )
    is_taken = bool(ticket.get("assigned_to_support_id"))
    try:
        await bot.edit_message_text(
            chat_id=config.support_group_id,
            message_id=msg_id,
            text=text,
            reply_markup=ticket_kb(ticket_id, is_taken=is_taken, status=status),
        )
    except (TelegramBadRequest, TelegramAPIError) as e:
        logger.debug("Не удалось обновить карточку тикета %s: %s", ticket_id, e)

async def send_warning_to_support(
    bot: Bot,
    ticket_id: int,
) -> None:
    """
    30 минут без ответа — мягкое предупреждение саппорту.
    Отправляется в тему тикета (если есть), иначе в общий чат.
    """
    if not config.support_group_id:
        logger.warning("SUPPORT_GROUP_ID не задан в .env")
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        return

    thread_id = ticket.get("support_thread_id")
    assigned_id = ticket.get("assigned_to_support_id")

    support_username = None
    if assigned_id:
        support_username = await get_client_username(assigned_id)

    text = f"""⚠️ SLA 30 минут
Ticket #{ticket_id}

Нет ответа клиенту более {config.sla_warning_minutes} минут.
{f"Ответственный: @{support_username}" if support_username else ""}
Пожалуйста, дайте ответ клиенту."""

    try:
        kwargs = {
            "chat_id": config.support_group_id,
            "text": text,
        }

        if thread_id:
            kwargs["message_thread_id"] = thread_id

        await bot.send_message(**kwargs)

    except (TelegramBadRequest, TelegramAPIError) as e:
        logger.warning(
            f"Не удалось отправить SLA-предупреждение по тикету #{ticket_id}: {e}"
        )


async def send_escalation_to_admin(
    bot: Bot,
    ticket_id: int,
    support_username: str,
    client_username: str,
    last_message: str,
    status: str,
) -> None:
    """Отправить эскалацию в Admin Chat."""
    if not config.admin_chat_id:
        logger.warning("ADMIN_CHAT_ID не задан в .env")
        return

    text = f"""⛔ Эскалация Ticket #{ticket_id}
Саппорт: @{support_username}
Клиент: @{client_username}
Последнее сообщение клиента: "{last_message[:300]}"
Статус: {status}"""

    try:
        await bot.send_message(config.admin_chat_id, text)
    except TelegramBadRequest as e:
        logger.error(
            f"Не удалось отправить эскалацию #{ticket_id} в Admin Chat: {e}. "
            f"Проверьте ADMIN_CHAT_ID и убедитесь, что бот добавлен в чат."
        )
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API при отправке эскалации #{ticket_id}: {e}")
