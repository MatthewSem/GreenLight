from aiogram import Router, F
from aiogram.types import Message
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import config
from services.db.statistik import get_avg_first_reply_time, get_avg_messages_before_reply, get_sla_violations, \
    get_leads_count, get_avg_reply_time
from services.db.tickets import get_all_supports
from services.db.users import get_user_role

router = Router(name="statistik")
TZ = ZoneInfo(config.timezone)


async def build_stats_block(date_from, date_to, tg_support: int | None = None) -> str:
    avg_seconds = await get_avg_first_reply_time(date_from, date_to, tg_support)
    avg_msg = await get_avg_messages_before_reply(date_from, date_to, tg_support)
    violations = await get_sla_violations(date_from, date_to, tg_support)
    leads = await get_leads_count(date_from, date_to, tg_support)
    avg_reply_seconds = await get_avg_reply_time(date_from, date_to, tg_support)
    if avg_seconds:
        minutes = int(avg_seconds // 60)
        seconds = int(avg_seconds % 60)
        avg_time_text = f"{minutes}м {seconds}с"
    else:
        avg_time_text = "—"

    if avg_reply_seconds:
        minutes = int(avg_reply_seconds // 60)
        seconds = int(avg_reply_seconds % 60)
        avg_reply_text = f"{minutes}м {seconds}с"
    else:
        avg_reply_text = "—"

    return (
        f"Лиды: {leads}\n"
        f"Среднее время ответа: {avg_time_text}\n"
        f"Среднее время первого ответа: {avg_time_text}\n"
        f"Среднее время ответа саппорта: {avg_reply_text}\n"
        # f"Сообщений до ответа: {avg_msg}\n"
        f"Нарушения SLA (>{config.sla_minutes} мин): {violations}"
    )

@router.message(F.chat.type == "private", F.text.startswith("/stats"))
async def cmd_stats_period(message: Message):
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])
    if role not in ("admin", "support"):
        await message.answer("⛔ Только админ или саппорт.")
        return
    parts = message.text.strip().split()
    if len(parts) != 3:
        await message.answer("/stats DD.MM.YYYY DD.MM.YYYY")
        return
    try:
        date_from = datetime.strptime(parts[1], "%d.%m.%Y").replace(tzinfo=TZ)
        date_to = datetime.strptime(parts[2], "%d.%m.%Y").replace(tzinfo=TZ) + timedelta(days=1)
    except ValueError:
        await message.answer("Неверный формат даты. Используйте DD.MM.YYYY")
        return
    if date_from >= date_to:
        await message.answer("Дата начала должна быть раньше конца")
        return
    if role == "support":
        text = f"[Ваша статистика]\n{await build_stats_block(date_from, date_to, tg_id)}"
    else:
        supports = await get_all_supports()
        blocks = []
        for s in supports:
            username = s.get("username") or "—"
            blocks.append(f"[SUPPORT] @{username}\n{await build_stats_block(date_from, date_to, s['tg_id'])}")
        blocks.append(f"[ВСЕ САППОРТЫ]\n{await build_stats_block(date_from, date_to)}")
        text = "\n\n".join(blocks)
    await message.answer(text)


@router.message(F.chat.type == "private", F.text == "/statistik")
async def cmd_statistik(message: Message):
    tg_id = message.from_user.id
    role = await get_user_role(tg_id, config.admin_ids or [])
    if role not in ("admin", "support"):
        await message.answer("⛔ Только админ или саппорт.")
        return

    now = datetime.now(tz=TZ)
    periods = [
        ("за день", now.replace(hour=0, minute=0, second=0, microsecond=0), now),
        ("за неделю", now - timedelta(days=7), now),
        ("за месяц", now - timedelta(days=30), now),
    ]

    blocks = []
    if role == "support":
        username = (await get_all_supports())
        supports_dict = {s["tg_id"]: s for s in username}
        username = supports_dict.get(tg_id, {}).get("username", "—")
        blocks.append(f"[SUPPORT] @{username}")
        for pname, df, dt in periods:
            blocks.append(f"[Статистика {pname}]\n{await build_stats_block(df, dt, tg_id)}")
    else:
        supports = await get_all_supports()
        for s in supports:
            uname = s.get("username") or "—"
            blocks.append(f"[SUPPORT] @{uname}")
            for pname, df, dt in periods:
                blocks.append(f"[Статистика {pname}]\n{await build_stats_block(df, dt, s['tg_id'])}")
        blocks.append("[ВСЕ САППОРТЫ]")
        for pname, df, dt in periods:
            blocks.append(f"[Статистика {pname}]\n{await build_stats_block(df, dt)}")
    await message.answer("\n\n".join(blocks))
