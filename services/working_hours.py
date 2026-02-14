"""Проверка рабочего времени (Europe/Moscow)."""
from datetime import datetime
import pytz

from config import config


def is_working_hours() -> bool:
    """Сейчас рабочее время? 10:00–22:00 МСК."""
    tz = pytz.timezone(config.timezone)
    now = datetime.now(tz).time()
    start = datetime.strptime(f"{config.work_start_hour}:00", "%H:%M").time()
    end = datetime.strptime(f"{config.work_end_hour}:00", "%H:%M").time()
    return start <= now < end


