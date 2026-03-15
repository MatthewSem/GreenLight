from keyboards import main_keyboard
from config import config
from services.db.referals import get_keyboard_version, set_keyboard_version
from services.db.users import get_user_role

KEYBOARD_VERSION = 3

async def ensure_actual_keyboard(bot, user_id: int, message_id: int | None = None):
    """
    Обновляет клавиатуру, если версия устарела.
    Для новых пользователей (message_id=None) просто сохраняем версию.
    Для активных пользователей — редактируем reply_markup без отправки текста.
    """
    current = await get_keyboard_version(user_id)
    if current == KEYBOARD_VERSION:
        return

    # Сохраняем новую версию в БД
    await set_keyboard_version(user_id, KEYBOARD_VERSION)

    # Если нет message_id — считаем, что пользователь только пришёл → ничего не отправляем
    if not message_id:
        return

    # Для активного пользователя — редактируем клавиатуру
    role = await get_user_role(user_id, config.admin_ids or [])
    try:
        await bot.edit_message_reply_markup(
            chat_id=user_id,
            message_id=message_id,
            reply_markup=main_keyboard(role)
        )
    except Exception:
        # Игнорируем ошибки (например, если сообщение старое или удалено)
        pass