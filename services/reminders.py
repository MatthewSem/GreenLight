import asyncio
from datetime import datetime, timedelta, timezone
from services.db import get_pool
from constants import ONE_PING_USER, TWO_PING_USER, FHREE_PING_USER, FOUR_PING_USER, FIVE_PING_USER

MESSAGES = [
    (30, ONE_PING_USER),
    (120, TWO_PING_USER),
    (1440, FHREE_PING_USER),
    (4320, FOUR_PING_USER),
    (10080, FIVE_PING_USER)
]

async def reminder_worker(bot):
    while True:
        await asyncio.sleep(600)  # проверяем каждые 30 сек для теста

        pool = get_pool()

        async with pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT u.tg_id,
                       u.created_at,
                       u.reminder_step,
                       u.client_type
                FROM users u
                WHERE u.reminder_step < 5
                  AND u.client_type = 'new'          -- не LEAD
                  AND u.created_at > NOW() - INTERVAL '7 days'
                  AND NOT EXISTS (                   -- нет тикета
                      SELECT 1 FROM tickets t
                      WHERE t.client_user_id = u.tg_id
                  )
            """)

        now = datetime.now(timezone.utc)

        for user in users:
            tg_id = user["tg_id"]
            created = user["created_at"]
            step = user["reminder_step"]
            client_type = user["client_type"]

            # дополнительная защита
            if client_type != "new":
                continue

            delta_minutes = (now - created).total_seconds() / 60

            if step < len(MESSAGES):
                required_minutes, text = MESSAGES[step]

                if delta_minutes >= required_minutes:

                    # 🔎 проверка — не ответил ли support
                    async with pool.acquire() as conn:
                        support_replied = await conn.fetchval("""
                            SELECT 1
                            FROM messages m
                            JOIN tickets t ON m.ticket_id = t.ticket_id
                            WHERE t.client_user_id = $1
                              AND m.direction = 'OUT'
                            LIMIT 1
                        """, tg_id)

                    if support_replied:
                        continue

                    try:
                        await bot.send_message(tg_id, text)

                        async with pool.acquire() as conn:
                            await conn.execute("""
                                UPDATE users
                                SET reminder_step = reminder_step + 1
                                WHERE tg_id = $1
                            """, tg_id)

                    except Exception:
                        pass