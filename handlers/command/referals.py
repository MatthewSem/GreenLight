from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from services.db import get_or_create_referral, get_user_role, get_user_id_by_username, get_user_id_by_username_referals
from config import config

router = Router(name="referals")

class CreateReferralFSM(StatesGroup):
    waiting_for_username = State()

@router.message(F.text.in_(["📎 Реферальная ссылка"]))
async def client_referral(message: Message):
    tg_id = message.from_user.id
    referral = await get_or_create_referral(owner_client_id=tg_id)
    await message.answer(f"Ваша реферальная ссылка:\n{referral['link']}")

@router.message(F.text.in_(["📌 Создать ссылку для клиента"]))
async def start_create_referral(message: Message, state: FSMContext):
    role = await get_user_role(message.from_user.id, config.admin_ids or [])
    if role not in ("admin", "support"):
        await message.answer("⛔ Только админ или саппорт.")
        return

    await message.answer("Введите username клиента, для которого нужно создать ссылку (без @):")
    await state.set_state(CreateReferralFSM.waiting_for_username)

@router.message(StateFilter(CreateReferralFSM.waiting_for_username))
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")  # убираем возможный @ в начале

    print(username)
    # Получаем TG ID пользователя по username
    client_id = await get_user_id_by_username_referals(username)
    if not client_id:
        await message.answer(f"❌ Пользователь с username @{username} не найден.")
        return

    # Создаем или получаем реферальную ссылку
    referral = await get_or_create_referral(owner_client_id=client_id, created_by=message.from_user.id)
    await message.answer(f"✅ Реферальная ссылка для @{username}:\n{referral['link']}")
    await state.clear()

