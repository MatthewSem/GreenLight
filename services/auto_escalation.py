import asyncio
import logging
from datetime import datetime, timezone

from services.db.sla import get_tickets_for_sla_check, update_ticket_sla_stage
from services.db.tickets import get_client_username
from services.working_hours import is_working_hours, working_minutes_between
from services.support_chat import send_escalation_to_admin, send_warning_to_support
from config import config

logger = logging.getLogger(__name__)
UTC = timezone.utc

async def escalation_watcher(bot):
    CHECK_INTERVAL = 300  # проверка каждые 5 минут

    while True:
        try:
            if not is_working_hours():
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            tickets = await get_tickets_for_sla_check()
            now = datetime.now(UTC)

            for t in tickets:
                ticket_id = t["ticket_id"]
                stage = t["sla_stage"] or 0

                # Определяем, с какого момента считать SLA
                if not t["taken_at"]:
                    start_time = t["created_at"]
                    mode = "take"  # никто не взял
                else:
                    # тикет взят — считаем с момента взятия
                    start_time = t["sla_started_at"]
                    mode = "reply"  # ждём ответа саппорта

                if start_time is None:
                    continue
                    
                minutes_passed = working_minutes_between(start_time, now)

                # ⚠️ Первая стадия: предупреждение саппорта
                if minutes_passed >= config.sla_warning_minutes and stage < 1:
                    await send_warning_to_support(bot, ticket_id)
                    await update_ticket_sla_stage(ticket_id, 1)

                # 🚨 Вторая стадия: эскалация админам
                elif minutes_passed >= config.sla_admin_minutes and stage < 2:
                    support_username = await get_client_username(
                        t["assigned_to_support_id"]
                    )
                    client_username = await get_client_username(
                        t["client_user_id"]
                    )
                    last_msg = "(тикет ещё не взят)" if mode == "take" else "Нет ответа от саппорта"
                    await send_escalation_to_admin(
                        bot,
                        ticket_id=ticket_id,
                        support_username=support_username,
                        client_username=client_username,
                        last_message=last_msg,
                        status=t["status"],
                    )
                    await update_ticket_sla_stage(ticket_id, 2)

                # 🔥 Критическая стадия
                elif minutes_passed >= config.sla_critical_minutes and stage < 3:
                    support_username = await get_client_username(
                        t["assigned_to_support_id"]
                    )
                    client_username = await get_client_username(
                        t["client_user_id"]
                    )
                    last_msg = "(тикет ещё не взят)" if mode == "take" else "КРИТИЧЕСКОЕ нарушение SLA"
                    await send_escalation_to_admin(
                        bot,
                        ticket_id=ticket_id,
                        support_username=support_username,
                        client_username=client_username,
                        last_message=last_msg,
                        status=t["status"],
                    )
                    await update_ticket_sla_stage(ticket_id, 3)

        except Exception as e:
            logger.exception("SLA watcher error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)