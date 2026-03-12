"""Проверка рабочего времени (Europe/Moscow)."""
from datetime import datetime, timedelta
import pytz
from config import config

tz = pytz.timezone(config.timezone)

WORK_START = config.work_start_hour
WORK_END = config.work_end_hour

def is_working_hours() -> bool:
    """Сейчас рабочее время? 10:00–22:00 МСК."""
    now = datetime.now(tz).time()

    start = datetime.strptime(f"{WORK_START}:00", "%H:%M").time()
    end = datetime.strptime(f"{WORK_END}:00", "%H:%M").time()
    return start <= now < end


def working_minutes_between(start: datetime, end: datetime) -> float:
    """
    Считает рабочие минуты между датами.
    Учитывает только 10:00–22:00 МСК.
    """

    start = start.astimezone(tz)
    end = end.astimezone(tz)

    total_minutes = 0
    current = start

    while current < end:

        work_start = current.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
        work_end = current.replace(hour=WORK_END, minute=0, second=0, microsecond=0)

        if current < work_start:
            current = work_start

        if current >= work_end:
            current = (current + timedelta(days=1)).replace(
                hour=WORK_START,
                minute=0,
                second=0,
                microsecond=0
            )
            continue

        period_end = min(work_end, end)

        total_minutes += (period_end - current).total_seconds() / 60
        current = period_end

    return total_minutes

