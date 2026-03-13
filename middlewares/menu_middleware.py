from aiogram import BaseMiddleware
from services.menu import ensure_actual_keyboard

class MenuMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data["bot"]

        if hasattr(event, "from_user"):
            user = event.from_user

            # Проверка: если это бот, ничего не делаем
            if not getattr(user, "is_bot", False):
                await ensure_actual_keyboard(bot, user.id)

        return await handler(event, data)