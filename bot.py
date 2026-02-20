"""Точка входа — запуск бота."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import config
from database import Database
from handlers import client, support, admin

from services.auto_escalation import escalation_watcher
from services.reminders import reminder_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Запуск бота."""
    if not config.bot_token:
        logger.error("BOT_TOKEN не задан. Создайте .env файл.")
        return

    await Database.connect()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.include_router(admin.router)   # admin первым — broadcast, set_role
    dp.include_router(support.router)  # support group
    dp.include_router(client.router)   # клиенты

    asyncio.create_task(escalation_watcher(bot))
    asyncio.create_task(reminder_worker(bot))

    # Команды бота (видны при вводе / в поле сообщения)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать диалог / поддержка"),
        BotCommand(command="help", description="Список команд с описанием"),
    ])


    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await Database.disconnect()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
