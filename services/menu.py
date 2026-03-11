from keyboards import main_keyboard
from services.db import get_user_role, get_keyboard_version, set_keyboard_version
from config import config

KEYBOARD_VERSION = 3


async def ensure_actual_keyboard(bot, user_id: int):
    current = await get_keyboard_version(user_id)

    if current == KEYBOARD_VERSION:
        return

    role = await get_user_role(user_id, config.admin_ids or [])

    await bot.send_message(
        user_id,
        "Я - бот, я пришел сказать, что меню обновлено."
        "Не переживай! Твое сообщение доставлено, а действие выполнено.",
        reply_markup=main_keyboard(role)
    )

    await set_keyboard_version(user_id, KEYBOARD_VERSION)