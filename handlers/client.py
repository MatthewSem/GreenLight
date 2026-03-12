"""Обработчики для клиентов."""
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject

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

from config import config
from services.db.onboarding import get_onboarding_state, start_onboarding, save_onboarding_answer, complete_onboarding
from services.db.sla import start_ticket_sla
from services.db.tickets import upsert_user_with_client_type, mark_user_active, add_message, \
    get_or_create_active_ticket, get_ticket, activate_ticket, set_client_type, set_ticket_card_message_id
from services.db.users import get_user_role, get_or_create_user
from services.working_hours import is_working_hours
from services.crm import send_lead_to_crm
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

def _get_client_label(client_type: ClientType) -> str:
    if client_type == ClientType.EXISTING:
        return "👤 Действующий"
    return "🆕 Новый"

@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, command=None):
    """Только приветствие. Тикет и онбординг — после первого ответа клиента на вопрос «Какой у вас вопрос?»."""
    tg_id = message.from_user.id
    username = message.from_user.username
    payload = getattr(command, "args", None)


    role = await get_user_role(tg_id, config.admin_ids or [])

    if role in ("support", "admin"):
        await message.answer(MSG_START_SUPPORT_ADMIN)
        await message.answer(
            "Вы вошли как оператор/администратор. Управление тикетами — в группе поддержки."
        )
        return

    if payload == "existing":
        await upsert_user_with_client_type(tg_id, username, ClientType.EXISTING)
        await message.answer(
            "🎉 Добро пожаловать!\nВы зарегистрированы как действующий клиент."
        )
    else:
        # Обычный /start без payload
        await get_or_create_user(tg_id, username, admin_ids=config.admin_ids or [])

        # Сообщение в любом случае
    await message.answer(MSG_START)

@router.message(
    F.chat.type == "private",
    F.text | F.photo | F.document | F.video | F.audio | F.voice,
)
async def client_message(message: Message):
    tg_id = message.from_user.id
    username = message.from_user.username

    user, client_type, is_paid = await get_or_create_user(tg_id, username)

    await mark_user_active(tg_id)
    text = message.text or message.caption or ""
    media_type, file_id = _get_media_info(message)
    last_msg = text or "(медиа)"

    # -------------------------------------------------
    # 1️⃣ ТИКЕТ СОЗДАЁТСЯ СРАЗУ (для истории)
    # -------------------------------------------------

    ticket_id, is_new_ticket = await get_or_create_active_ticket(tg_id)

    await add_message(
        ticket_id,
        "IN",
        tg_id,
        text=last_msg,
        media_type=media_type,
        media_file_id=file_id,
    )

    ticket = await get_ticket(ticket_id)

    if ticket["taken_at"]:
        await start_ticket_sla(ticket_id)

    if not is_working_hours():
        await message.answer(MSG_OFFLINE)

    # -------------------------------------------------
    # 2️⃣ NEW → запускаем онбординг
    # -------------------------------------------------

    if client_type == ClientType.NEW:
        state = await get_onboarding_state(tg_id)

        # если онбординг ещё не начат
        if not state:
            await message.answer(MSG_TICKET_RECEIVED)
            if not is_working_hours():
                await message.answer(MSG_OFFLINE)

            await message.answer(MSG_ONBOARDING_START)
            await message.answer(f"1. {ONBOARDING_QUESTIONS[0]}")
            await start_onboarding(tg_id)
            return

        # если онбординг уже идёт
        step = int(state["current_step"])

        answer = {"text": text}
        if media_type and file_id:
            answer["media_type"] = media_type
            answer["media_file_id"] = file_id

        await save_onboarding_answer(tg_id, step, answer)

        next_step = step + 1

        # если вопросы закончились
        if next_step > len(ONBOARDING_QUESTIONS):
            raw = state.get("answers") or {}
            if isinstance(raw, str):
                raw = json.loads(raw) if raw else {}
            raw[str(step)] = answer

            lead_id = await complete_onboarding(tg_id, raw)

            await activate_ticket(ticket_id)

            # переводим NEW → LEAD
            await set_client_type(tg_id, ClientType.LEAD)

            await send_lead_to_crm(lead_id, tg_id, username, raw)

            await message.answer(MSG_ONBOARDING_DONE)

            # теперь support может видеть тикет
            client_label = _get_client_label(ClientType.LEAD)

            card_msg_id = await send_ticket_to_support_group(
                bot=message.bot,
                ticket_id=ticket_id,
                client_tg_id=tg_id,
                username=username or "—",
                client_type_label=client_label,
                last_message=last_msg,
            )

            await start_ticket_sla(ticket_id)

            if card_msg_id:
                await set_ticket_card_message_id(ticket_id, card_msg_id)
                await update_ticket_card(
                    message.bot,
                    ticket_id,
                    last_message=last_msg,
                )

            return

        # иначе задаём следующий вопрос
        next_q = ONBOARDING_QUESTIONS[step]
        await message.answer(f"{next_step}. {next_q}")
        return

    # -------------------------------------------------
    # 3️⃣ LEAD и EXISTING → support видит тикет
    # -------------------------------------------------

    client_label = _get_client_label(client_type)

    if is_new_ticket:
        await message.answer(MSG_TICKET_RECEIVED)
        if not is_working_hours():
            await message.answer(MSG_OFFLINE)

        card_msg_id = await send_ticket_to_support_group(
            bot=message.bot,
            ticket_id=ticket_id,
            client_tg_id=tg_id,
            username=username or "—",
            client_type_label=client_label,
            last_message=last_msg,
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
                last_message=last_msg,
            )