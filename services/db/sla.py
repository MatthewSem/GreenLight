"""Операции с БД."""
from database import get_pool

async def start_ticket_sla(ticket_id: int):
    """
    Запустить SLA (клиент написал сообщение).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tickets
            SET sla_started_at = NOW(),
                sla_stage = 0
            WHERE ticket_id = $1
            """,
            ticket_id,
        )

async def stop_ticket_sla(ticket_id: int):
    """
    Остановить SLA (саппорт ответил).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tickets
            SET sla_started_at = NULL
            WHERE ticket_id = $1
            """,
            ticket_id,
        )


async def update_ticket_sla_stage(ticket_id: int, stage: int):
    """
    Обновить SLA-стадию тикета.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE tickets
            SET sla_stage = $2
            WHERE ticket_id = $1
        """, ticket_id, stage)

async def get_tickets_for_sla_check():
    """
    Получить тикеты, для которых запущен SLA и нет первого ответа.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM tickets
            WHERE status IN ('OPEN', 'WAITING')
        """)
    return [dict(r) for r in rows]
