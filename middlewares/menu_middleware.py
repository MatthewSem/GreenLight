from aiogram import BaseMiddleware
from services.menu import ensure_actual_keyboard

class MenuMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data["bot"]

        if hasattr(event, "from_user") and not getattr(event.from_user, "is_bot", False):
            user_id = event.from_user.id

            # Проверяем, есть ли у события message_id — только для активных сообщений редактируем клавиатуру
            message_id = getattr(event, "message_id", None)
            await ensure_actual_keyboard(bot, user_id, message_id)

        return await handler(event, data)