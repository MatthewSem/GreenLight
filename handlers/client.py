"""Обработчики для клиентов."""
import json
from aiogram import Router, F
from aiogram.types import Message
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
from keyboards import main_keyboard
from config import config
from services.db.onboarding import get_onboarding_state, start_onboarding, save_onboarding_answer, complete_onboarding
from services.db.referals import get_referral_by_code, create_referral_usage
from services.db.sla import start_ticket_sla
from services.db.tickets import upsert_user_with_client_type, mark_user_active, add_message, \
    get_or_create_active_ticket, get_ticket, activate_ticket, set_client_type, set_ticket_card_message_id, \
    update_created_at_for_draft_on_open
from services.db.users import get_user_role, get_or_create_user
from services.menu import ensure_actual_keyboard
from services.working_hours import is_working_hours
from services.crm import send_lead_to_crm
from services.support_chat import (
    send_ticket_to_support_group,
    send_new_client_message_to_topic,
    update_ticket_card,
)
from utils.media_extractor import extract_media

router = Router(name="client")

def _get_client_label(client_type: ClientType) -> str:
    if client_type == ClientType.EXISTING:
        return "👤 Действующий"
    return "🆕 Новый"

async def is_admin_or_support(tg_id: int) -> bool:
    role = await get_user_role(tg_id, config.admin_ids or [])
    return role in ("support", "admin"), role

def get_text_and_media(message: Message):
    text = message.text or message.caption or ""
    media_type, file_id = extract_media(message)
    last_msg = text or "(медиа)"
    return text, media_type, file_id, last_msg

async def send_ticket(bot, ticket_id, tg_id, username, client_type, last_msg):
    client_label = _get_client_label(client_type)
    card_msg_id = await send_ticket_to_support_group(
        bot=bot,
        ticket_id=ticket_id,
        client_tg_id=tg_id,
        username=username or "—",
        client_type_label=client_label,
        last_message=last_msg,
    )
    if card_msg_id:
        await set_ticket_card_message_id(ticket_id, card_msg_id)
        await update_ticket_card(bot, ticket_id, last_message=last_msg)

async def handle_onboarding(message: Message, tg_id: int, username: str, text: str, media_type=None, file_id=None, ticket_id=None):
    state = await get_onboarding_state(tg_id)
    if not state:
        await message.answer(MSG_TICKET_RECEIVED)
        if not is_working_hours():
            await message.answer(MSG_OFFLINE)
        await message.answer(MSG_ONBOARDING_START)
        await message.answer(f"1. {ONBOARDING_QUESTIONS[0]}")
        await start_onboarding(tg_id)
        return True  # завершено
    step = int(state["current_step"])
    answer = {"text": text}
    if media_type and file_id:
        answer["media_type"] = media_type
        answer["media_file_id"] = file_id
    await save_onboarding_answer(tg_id, step, answer)

    next_step = step + 1
    if next_step > len(ONBOARDING_QUESTIONS):
        raw = state.get("answers") or {}
        if isinstance(raw, str):
            raw = json.loads(raw) if raw else {}
        raw[str(step)] = answer
        lead_id = await complete_onboarding(tg_id, raw)
        await activate_ticket(ticket_id)
        await set_client_type(tg_id, ClientType.LEAD)
        await send_lead_to_crm(lead_id, tg_id, username, raw)
        await message.answer(MSG_ONBOARDING_DONE)

        await send_ticket(message.bot, ticket_id, tg_id, username, ClientType.LEAD, text)
        await update_created_at_for_draft_on_open(ticket_id)
        await start_ticket_sla(ticket_id)
        return True
    else:
        next_q = ONBOARDING_QUESTIONS[step]
        await message.answer(f"{next_step}. {next_q}")
        return True

@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, command=None):
    """Только приветствие. Тикет и онбординг — после первого ответа клиента на вопрос «Какой у вас вопрос?»."""
    tg_id = message.from_user.id
    username = message.from_user.username
    payload = getattr(command, "args", None)

    # 1️⃣ Проверяем, админ или саппорт
    is_admin, role = await is_admin_or_support(tg_id)
    if is_admin:
        await message.answer(MSG_START_SUPPORT_ADMIN, reply_markup=main_keyboard(role))
        await message.answer(
            "Вы вошли как оператор/администратор. Управление тикетами — в группе поддержки."
        )
        return

    # 2️⃣ Создаём пользователя с дефолтным client_type=NEW
    await get_or_create_user(tg_id, username, admin_ids=config.admin_ids or [])

    # 3️⃣ Обрабатываем реферальный код
    if payload:
        referral = await get_referral_by_code(payload)  # Функция ищет по коду в таблице referrals
        if referral:
            await create_referral_usage(
                referral_id=referral['referral_id'],
                visitor_client_id=tg_id,
                converted=True  # пользователь зарегистрировался
            )
            await message.answer(f"🎉 Вы пришли по реферальной ссылке @{referral['owner_username']}!")

    # 4️⃣ Обновляем тип клиента, если payload == "existing"
    if payload == "existing":
        await upsert_user_with_client_type(tg_id, username, ClientType.EXISTING)
        await message.answer(
            "🎉 Добро пожаловать!\nВы зарегистрированы как действующий клиент."
        )

    # Сохраняем версию клавиатуры без отправки нового текста
    await ensure_actual_keyboard(message.bot, tg_id)

    # 5️⃣ Всегда отправляем приветственное сообщение
    await message.answer(MSG_START, reply_markup=main_keyboard(role))

@router.message(
    F.chat.type == "private",
    F.text | F.photo | F.document | F.video | F.audio | F.voice,
)
async def client_message(message: Message):

    tg_id = message.from_user.id
    username = message.from_user.username

    # Тут уже пользователь активный, message_id есть
    await ensure_actual_keyboard(message.bot, tg_id, message.message_id)

    # 1️⃣ Проверяем, админ или саппорт
    is_admin, role = await is_admin_or_support(tg_id)
    if is_admin:
        await message.answer(MSG_START_SUPPORT_ADMIN, reply_markup=main_keyboard(role))
        await message.answer(
            "Вы вошли как оператор/администратор. Тикеты через этого бота не создаются."
        )
        return

    # 2️⃣ Создаём пользователя (или получаем) один раз
    user_data, client_type, _ = await get_or_create_user(tg_id, username, admin_ids=config.admin_ids or [])

    # 3️⃣ Получаем текст и медиа
    text, media_type, file_id, last_msg = get_text_and_media(message)

    # 4️⃣ Создаём/обрабатываем тикет
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

    # 5️⃣ NEW → запускаем онбординг
    if client_type == ClientType.NEW:
        completed = await handle_onboarding(
            message, tg_id, username, text, media_type, file_id, ticket_id
        )
        if completed:
            return

    # 6️⃣ LEAD и EXISTING → support видит тикет
    else:
        if not is_working_hours():
            await message.answer(MSG_OFFLINE)

        client_label = _get_client_label(client_type)

        if is_new_ticket:
            await message.answer(MSG_TICKET_RECEIVED)
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
            if ticket.get("support_thread_id"):
                await send_new_client_message_to_topic(
                    bot=message.bot,
                    ticket_id=ticket_id,
                    support_thread_id=ticket["support_thread_id"],
                    text=last_msg,
                    media_type=media_type,
                    media_file_id=file_id,
                )
            else:
                await update_ticket_card(
                    message.bot,
                    ticket_id,
                    last_message=last_msg,
                )