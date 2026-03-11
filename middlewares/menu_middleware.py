from aiogram import BaseMiddleware
from services.menu import ensure_actual_keyboard

class MenuMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):

        bot = data["bot"]

        if hasattr(event, "from_user"):
            user_id = event.from_user.id
            await ensure_actual_keyboard(bot, user_id)

        return await handler(event, data)