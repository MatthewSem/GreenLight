"""Обработчики для клиентов."""
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.filters import CommandStart

from constants import (
    ClientType,
    MSG_START,
    MSG_ONBOARDING_START,
    MSG_ONBOARDING_DONE,
    MSG_TICKET_RECEIVED,
    MSG_OFFLINE,
    ONBOARDING_QUESTIONS,
    MSG_START_SUPPORT_ADMIN,
)
from services.db import (
    get_or_create_user,
    get_onboarding_state,
    save_onboarding_answer,
    complete_onboarding,
    transfer_onboarding,
    get_or_create_active_ticket,
    add_message,
    get_ticket,
    set_ticket_card_message_id,
)
from config import config
from services.working_hours import is_working_hours
from services.crm import send_lead_to_crm
from keyboards import onboarding_transfer_kb
from services.support_chat import (
    send_ticket_to_support_group,
    send_new_client_message_to_topic,
    update_ticket_card,
)

router = Router(name="client")


def _get_media_info(message: Message) -> tuple[str | None, str | None]:
    """Получить media_type и file_id из сообщения."""
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.document:
        return "document", message.document.file_id
    if message.video:
        return "video", message.video.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.voice:
        return "voice", message.voice.file_id
    return None, None


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message):
    """Только приветствие. Тикет и онбординг — после первого ответа клиента на вопрос «Какой у вас вопрос?»."""
    tg_id = message.from_user.id
    username = message.from_user.username

    from services.db import get_user_role
    role = await get_user_role(tg_id, config.admin_ids or [])

    if role in ("support", "admin"):
        await message.answer(MSG_START_SUPPORT_ADMIN)
        await message.answer(
            "Вы вошли как оператор/администратор. Управление тикетами — в группе поддержки."
        )
        return

    await get_or_create_user(tg_id, username, admin_ids=config.admin_ids or [])
    await message.answer(MSG_START)


@router.callback_query(F.data == "onboarding:transfer")
async def onboarding_transfer(cb: CallbackQuery):
    """Кнопка «Передать оператору» во время онбординга."""
    tg_id = cb.from_user.id
    await cb.answer()

    ticket_id, lead_id, answers = await transfer_onboarding(tg_id)

    username = cb.from_user.username or "—"

    # CRM (webhook и/или Google Sheets)
    await send_lead_to_crm(lead_id, tg_id, username, answers)

    # Тикет в Support Group
    card_msg_id = await send_ticket_to_support_group(
        bot=cb.message.bot,
        ticket_id=ticket_id,
        client_tg_id=tg_id,
        username=username,
        client_type_label="🆕 Новый",
        last_message="(онбординг прерван, передано оператору)",
    )
    if card_msg_id:
        await set_ticket_card_message_id(ticket_id, card_msg_id)

    await cb.message.answer(MSG_TICKET_RECEIVED)
    if not is_working_hours():
        await cb.message.answer(MSG_OFFLINE)


@router.message(
    F.chat.type == "private",
    F.text | F.photo | F.document | F.video | F.audio | F.voice,
)
async def client_message(message: Message):
    """Обработка любых сообщений от клиента: онбординг и тикеты."""
    tg_id = message.from_user.id
    username = message.from_user.username

    from services.db import get_user_role
    role = await get_user_role(tg_id, config.admin_ids or [])
    if role in ("support", "admin"):
        return  # для саппорта/админов обработка не нужна

    # Получаем пользователя и его статус
    user, client_type, is_paid = await get_or_create_user(
        tg_id, username, admin_ids=config.admin_ids or []
    )
    state = await get_onboarding_state(tg_id)

    # 🔹 Если клиент уже существующий — онбординг игнорируем
    if client_type == ClientType.EXISTING:
        state = None

    # 🔹 Если клиент новый, онбординг не в процессе, но он уже завершён — не показываем снова
    if client_type == ClientType.NEW and not state and is_paid:
        # просто создаём тикет и добавляем сообщение
        ticket_id, is_new_ticket = await get_or_create_active_ticket(tg_id)
        text = message.text or message.caption or ""
        media_type, file_id = _get_media_info(message)
        last_msg = text or "(медиа)"

        await add_message(ticket_id, "IN", tg_id, text=last_msg, media_type=media_type, media_file_id=file_id)

        # уведомляем support если тикет новый
        if is_new_ticket:
            await message.answer(MSG_TICKET_RECEIVED)
            if not is_working_hours():
                await message.answer(MSG_OFFLINE)
            card_msg_id = await send_ticket_to_support_group(
                bot=message.bot,
                ticket_id=ticket_id,
                client_tg_id=tg_id,
                username=username or "—",
                client_type_label="🆕 Новый",
                last_message=last_msg,
            )
            if card_msg_id:
                await set_ticket_card_message_id(ticket_id, card_msg_id)
        return

    # 🔹 Онбординг в процессе
    if state:
        step = state["current_step"]
        if step <= len(ONBOARDING_QUESTIONS):
            media_type, file_id = _get_media_info(message)
            text = message.text or message.caption or ""
            answer = {"text": text}
            if media_type and file_id:
                answer["media_type"] = media_type
                answer["media_file_id"] = file_id

            await save_onboarding_answer(tg_id, step, answer)

            ticket_id, _ = await get_or_create_active_ticket(tg_id)
            last_msg = text or "(медиа)"
            await add_message(ticket_id, "IN", tg_id, text=last_msg, media_type=media_type, media_file_id=file_id)
            await update_ticket_card(message.bot, ticket_id, last_message=last_msg)

            # завершение онбординга
            if step == len(ONBOARDING_QUESTIONS):
                raw = state.get("answers") or {}
                if isinstance(raw, str):
                    raw = json.loads(raw) if raw else {}
                raw[str(step)] = answer

                lead_id = await complete_onboarding(tg_id, raw)
                await send_lead_to_crm(lead_id, tg_id, username, raw)

                # тикет в support после завершения онбординга
                card_msg_id = await send_ticket_to_support_group(
                    bot=message.bot,
                    ticket_id=ticket_id,
                    client_tg_id=tg_id,
                    username=username or "—",
                    client_type_label="🆕 Новый",
                    last_message=last_msg,
                )
                if card_msg_id:
                    await set_ticket_card_message_id(ticket_id, card_msg_id)

                await message.answer(MSG_ONBOARDING_DONE)
                await message.answer(MSG_TICKET_RECEIVED)
                if not is_working_hours():
                    await message.answer(MSG_OFFLINE)
            else:
                # следующий вопрос
                next_q = ONBOARDING_QUESTIONS[step]
                await message.answer(
                    f"{step + 1}. {next_q}",
                    reply_markup=onboarding_transfer_kb(),
                )
        return

    # 🔹 Новый клиент, онбординг не в процессе, ещё не завершён → старт онбординга
    if client_type == ClientType.NEW and not state and not is_paid:
        text = message.text or message.caption or ""
        media_type, file_id = _get_media_info(message)
        last_msg = text or "(медиа)"

        ticket_id, _ = await get_or_create_active_ticket(tg_id)
        await add_message(ticket_id, "IN", tg_id, text=last_msg, media_type=media_type, media_file_id=file_id)

        await message.answer(MSG_TICKET_RECEIVED)
        if not is_working_hours():
            await message.answer(MSG_OFFLINE)
        await message.answer(MSG_ONBOARDING_START, reply_markup=onboarding_transfer_kb())
        await message.answer(f"1. {ONBOARDING_QUESTIONS[0]}", reply_markup=onboarding_transfer_kb())

        from services.db import start_onboarding
        await start_onboarding(tg_id)
        return

    # 🔹 Действующий клиент после онбординга и/или оплаты → тикет
    ticket_id, is_new_ticket = await get_or_create_active_ticket(tg_id)
    text = message.text or message.caption or ""
    media_type, file_id = _get_media_info(message)

    await add_message(ticket_id, "IN", tg_id, text=text or "(медиа)", media_type=media_type, media_file_id=file_id)

    if is_new_ticket:
        await message.answer(MSG_TICKET_RECEIVED)
        if not is_working_hours():
            await message.answer(MSG_OFFLINE)
        card_msg_id = await send_ticket_to_support_group(
            bot=message.bot,
            ticket_id=ticket_id,
            client_tg_id=tg_id,
            username=username or "—",
            client_type_label="👤 Действующий",
            last_message=text or "(медиа)",
        )
        if card_msg_id:
            await set_ticket_card_message_id(ticket_id, card_msg_id)
    else:
        ticket = await get_ticket(ticket_id)
        if ticket and ticket.get("support_thread_id"):
            await send_new_client_message_to_topic(
                bot=message.bot,
                ticket_id=ticket_id,
                support_thread_id=ticket["support_thread_id"],
                text=text,
                media_type=media_type,
                media_file_id=file_id,
            )
        else:
            await update_ticket_card(
                message.bot,
                ticket_id,
                last_message=text or "(медиа)",
                client_type_label="👤 Действующий",
            )
