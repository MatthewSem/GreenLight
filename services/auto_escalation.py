"""Проверка поддержки и экскалация в случае игнорирования в течение 12 часов."""
from services.db import get_client_username, get_tickets_for_sla_check, update_ticket_sla_stage
import asyncio
import logging
from services.working_hours import is_working_hours
from datetime import datetime, timezone
from config import config
from services.support_chat import (
    send_escalation_to_admin,
    send_warning_to_support
)

logger = logging.getLogger(__name__)

UTC = timezone.utc

async def escalation_watcher(bot):
    CHECK_INTERVAL = 300  # 5 минут

    while True:
        try:
            if not is_working_hours():
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            tickets = await get_tickets_for_sla_check()
            now = datetime.now(UTC)

            for t in tickets:
                created = t["sla_started_at"]
                if not created:
                    continue
                minutes_passed = (now - created).total_seconds() / 60
                stage = t["sla_stage"] or 0

                # 30 минут — предупреждение саппорту
                if minutes_passed >= config.sla_warning_minutes and stage < 1:
                    await send_warning_to_support(bot, t["ticket_id"])
                    await update_ticket_sla_stage(t["ticket_id"], 1)

                # 60 минут — админу
                elif minutes_passed >= config.sla_admin_minutes and stage < 2:
                    await send_escalation_to_admin(
                        bot,
                        ticket_id=t["ticket_id"],
                        support_username=await get_client_username(t["assigned_to_support_id"]),
                        client_username=await get_client_username(t["client_user_id"]),
                        last_message="Нет ответа 60 минут",
                        status=t["status"],
                    )
                    await update_ticket_sla_stage(t["ticket_id"], 2)

                # 120 минут — критическая
                elif minutes_passed >= config.sla_critical_minutes and stage < 3:
                    await send_escalation_to_admin(
                        bot,
                        ticket_id=t["ticket_id"],
                        support_username=await get_client_username(t["assigned_to_support_id"]),
                        client_username=await get_client_username(t["client_user_id"]),
                        last_message="КРИТИЧЕСКОЕ нарушение SLA (120 мин)",
                        status=t["status"],
                    )
                    await update_ticket_sla_stage(t["ticket_id"], 3)

        except Exception as e:
            logger.exception("SLA watcher error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)

