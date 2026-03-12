"""Операции с БД."""
from typing import Optional, Tuple, List
import json
import datetime
from config import config

from database import get_pool
from constants import ClientType, TicketStatus


# =====================================
# Количество лидов
# =====================================
async def get_leads_count(date_from: datetime, date_to: datetime, tg_id: Optional[int] = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = "SELECT COUNT(*) AS total FROM tickets WHERE created_at BETWEEN $1 AND $2"
        params = [date_from, date_to]

        if tg_id:
            sql += " AND assigned_to_support_id = $3"
            params.append(tg_id)

        row = await conn.fetchrow(sql, *params)

    return row["total"] if row else 0

# =====================================
# Среднее время первого ответа
# =====================================
async def get_avg_first_reply_time(date_from: datetime, date_to: datetime, tg_id: Optional[int] = None) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = """
            SELECT AVG(EXTRACT(EPOCH FROM (first_reply_at - created_at))) AS avg_seconds
            FROM tickets
            WHERE first_reply_at IS NOT NULL
              AND created_at BETWEEN $1 AND $2
        """
        params = [date_from, date_to]

        if tg_id:
            sql += " AND assigned_to_support_id = $3"
            params.append(tg_id)

        row = await conn.fetchrow(sql, *params)

    if not row or not row["avg_seconds"]:
        return None
    return int(row["avg_seconds"])

# =====================================
# Нарушения SLA
# =====================================
async def get_sla_violations(date_from: datetime, date_to: datetime, tg_id: Optional[int] = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = """
            SELECT COUNT(*) AS violations
            FROM tickets
            WHERE first_reply_at IS NOT NULL
              AND created_at BETWEEN $1 AND $2
              AND (first_reply_at - created_at) > ($3 || ' minutes')::interval
        """
        params = [date_from, date_to, str(config.sla_minutes)]

        if tg_id:
            sql += " AND assigned_to_support_id = $4"
            params.append(tg_id)

        row = await conn.fetchrow(sql, *params)

    return row["violations"] if row else 0


# =====================================
# Среднее количество сообщений до ответа
# =====================================
async def get_avg_messages_before_reply(date_from: datetime, date_to: datetime, tg_id: Optional[int] = None) -> Optional[float]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = """
            SELECT AVG(msg_count)::numeric(10,2) AS avg_messages
            FROM (
                SELECT t.ticket_id,
                       COUNT(m.*) AS msg_count
                FROM tickets t
                LEFT JOIN messages m
                    ON m.ticket_id = t.ticket_id
                   AND m.direction = 'IN'  -- только сообщения от клиента
                   AND m.created_at <= t.first_reply_at
                WHERE t.first_reply_at IS NOT NULL
                  AND t.created_at BETWEEN $1 AND $2
        """
        params = [date_from, date_to]

        if tg_id:
            sql += " AND t.assigned_to_support_id = $3"
            params.append(tg_id)

        sql += " GROUP BY t.ticket_id) sub"
        row = await conn.fetchrow(sql, *params)

    return float(row["avg_messages"]) if row and row["avg_messages"] else None

