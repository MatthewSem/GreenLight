"""Операции с БД."""
from typing import Optional, Tuple, List
import json
import datetime
from config import config

from database import get_pool
from constants import ClientType, TicketStatus

async def get_or_create_user(
    tg_id: int,
    username: str | None = None,
    role: str = "client",
    admin_ids: list[int] | None = None,
) -> tuple[dict, ClientType, bool]:

    pool = get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE tg_id = $1",
            tg_id
        )

        if row:
            await conn.execute(
                """
                UPDATE users
                SET username = $1,
                    last_seen = NOW()
                WHERE tg_id = $2
                """,
                username or row["username"],
                tg_id
            )

            row = await conn.fetchrow(
                "SELECT * FROM users WHERE tg_id = $1",
                tg_id
            )

            client_type = ClientType(row["client_type"])
            is_paid = row.get("is_paid", False)

            return dict(row), client_type, is_paid

        # если пользователя нет
        initial_role = "admin" if (admin_ids and tg_id in admin_ids) else role

        await conn.execute(
            """
            INSERT INTO users (tg_id, username, role, client_type, is_blocked, is_paid)
            VALUES ($1, $2, $3, $4, FALSE, FALSE)
            """,
            tg_id,
            username,
            initial_role,
            ClientType.NEW.value,
        )

        row = await conn.fetchrow(
            "SELECT * FROM users WHERE tg_id = $1",
            tg_id
        )

        return dict(row), ClientType.NEW, False



async def get_user_client_type(tg_id: int) -> str:
    """Вернуть тип клиента для карточки: 'new' или 'existing' (по users.client_type / онбордингу)."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT client_type, onboarding_completed_at FROM users WHERE tg_id = $1", tg_id
    )
    if not row:
        return "new"
    ct = row.get("client_type")
    if ct == ClientType.EXISTING.value:
        return "existing"
    if row.get("onboarding_completed_at") is not None:
        return "existing"
    return "new"


async def get_user_role(tg_id: int, admin_ids: list[int] | None = None) -> Optional[str]:
    """Получить роль пользователя. admin_ids — первичные админы из config."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT role FROM users WHERE tg_id = $1", tg_id)
    if row:
        return row["role"]
    if admin_ids and tg_id in admin_ids:
        return "admin"
    return None


async def start_onboarding(tg_id: int) -> None:
    """Начать онбординг — создать/сбросить состояние."""
    await get_or_create_user(tg_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO onboarding_state (tg_id, current_step, answers)
               VALUES ($1, 1, '{}')
               ON CONFLICT (tg_id) DO UPDATE SET current_step = 1, answers = '{}'""",
            tg_id
        )


async def get_onboarding_state(tg_id: int) -> Optional[dict]:
    """Получить состояние онбординга."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM onboarding_state WHERE tg_id = $1", tg_id
    )
    return dict(row) if row else None


async def save_onboarding_answer(tg_id: int, step: int, answer: str | dict) -> None:
    """Сохранить ответ онбординга и перейти к следующему шагу."""
    pool = get_pool()
    async with pool.acquire() as conn:
        state = await conn.fetchrow(
            "SELECT answers FROM onboarding_state WHERE tg_id = $1", tg_id
        )
        answers = state["answers"] or {}
        if isinstance(answers, str):
            answers = json.loads(answers) if answers else {}
        answers[str(step)] = answer
        next_step = step + 1
        await conn.execute(
            """UPDATE onboarding_state SET current_step = $1, answers = $2
               WHERE tg_id = $3""",
            next_step, json.dumps(answers, ensure_ascii=False), tg_id
        )

async def complete_onboarding(tg_id: int, answers: dict) -> int:
    """
    Завершить онбординг: обновить user, создать lead, очистить state.
    Возвращает lead_id.
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        await get_or_create_user(tg_id)
        await conn.execute(
            """UPDATE users SET onboarding_completed_at = NOW(), client_type = $1
               WHERE tg_id = $2""",
            ClientType.LEAD.value, tg_id
        )
        lead_id = await conn.fetchval(
            """INSERT INTO leads (tg_id, answers, status)
               VALUES ($1, $2, 'NEW_LEAD') RETURNING lead_id""",
            tg_id, json.dumps(answers, ensure_ascii=False)
        )
        await conn.execute("DELETE FROM onboarding_state WHERE tg_id = $1", tg_id)
        return lead_id

async def mark_user_as_paid(tg_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE users
        SET is_paid = TRUE,
            client_type = $1
        WHERE tg_id = $2
        """,
        ClientType.EXISTING.value,
        tg_id
    )

async def get_or_create_active_ticket(client_tg_id: int) -> tuple[int, bool]:
    """
    Получить активный тикет или создать новый.
    Возвращает (ticket_id, is_new).
    """
    await get_or_create_user(client_tg_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        open_ticket = await conn.fetchrow(
            """SELECT ticket_id FROM tickets
               WHERE client_user_id = $1 AND status IN ('OPEN', 'WAITING')""",
            client_tg_id
        )
        if open_ticket:
            return open_ticket["ticket_id"], False

        ticket_id = await conn.fetchval(
            """INSERT INTO tickets (client_user_id, status) VALUES ($1, 'OPEN')
               RETURNING ticket_id""",
            client_tg_id
        )
        return ticket_id, True


async def add_message(
    ticket_id: int, direction: str, author_user_id: int | None,
    text: str | None = None, media_type: str | None = None, media_file_id: str | None = None
) -> None:
    """Добавить сообщение в тикет."""
    pool = get_pool()
    await pool.execute(
        """INSERT INTO messages (ticket_id, direction, author_user_id, text, media_type, media_file_id)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        ticket_id, direction, author_user_id, text, media_type, media_file_id
    )


async def take_ticket(ticket_id: int, support_tg_id: int) -> bool:
    """Взять тикет. False если уже взят."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT assigned_to_support_id FROM tickets WHERE ticket_id = $1", ticket_id
    )
    if not row or row["assigned_to_support_id"]:
        return False
    await pool.execute(
        """UPDATE tickets SET assigned_to_support_id = $1, taken_at = NOW(), status = 'WAITING'
           WHERE ticket_id = $2""",
        support_tg_id, ticket_id
    )
    return True


async def set_ticket_thread_id(ticket_id: int, thread_id: int) -> None:
    """Сохранить ID темы (топика) для тикета."""
    pool = get_pool()
    await pool.execute(
        "UPDATE tickets SET support_thread_id = $1 WHERE ticket_id = $2",
        thread_id, ticket_id
    )


async def get_users_by_type(client_type: str) -> list[int]:
    """
    Возвращает список tg_id пользователей по client_type:
    NEW, EXISTING, LEAD
    """
    pool = get_pool()

    rows = await pool.fetch(
        "SELECT tg_id FROM users WHERE client_type = $1",
        client_type.upper()
    )

    return [row["tg_id"] for row in rows]


async def set_ticket_card_message_id(ticket_id: int, message_id: int) -> None:
    """Сохранить message_id карточки тикета в общем чате (для последующего удаления)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE tickets SET ticket_card_message_id = $1 WHERE ticket_id = $2",
        message_id, ticket_id
    )


async def set_ticket_topic_card_message_id(ticket_id: int, message_id: int) -> None:
    """Сохранить message_id карточки тикета в топике (для обновления при смене статуса)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE tickets SET ticket_topic_card_message_id = $1 WHERE ticket_id = $2",
        message_id, ticket_id
    )


async def get_ticket_by_thread_id(thread_id: int) -> Optional[dict]:
    """Найти тикет по ID темы в чате поддержки."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM tickets WHERE support_thread_id = $1", thread_id
    )
    return dict(row) if row else None


async def set_first_reply_if_needed(ticket_id: int) -> None:
    """Установить first_reply_at если ещё не установлен."""
    pool = get_pool()
    await pool.execute(
        """UPDATE tickets
           SET first_reply_at = COALESCE(first_reply_at, NOW()),
            sla_stage=0
           WHERE ticket_id = $1""",
        ticket_id
    )


async def update_ticket_status(ticket_id: int, status: str) -> None:
    """Обновить статус тикета."""
    if status not in {s.value for s in TicketStatus}:
        raise ValueError("Invalid ticket status")

    pool = get_pool()
    if status == TicketStatus.CLOSED.value:
        await pool.execute(
            """UPDATE tickets
               SET status = $1, closed_at = NOW()
               WHERE ticket_id = $2""",
            status, ticket_id
        )
    else:
        await pool.execute(
            """UPDATE tickets
               SET status = $1, closed_at = NULL
               WHERE ticket_id = $2""",
            status, ticket_id
        )

async def get_ticket(ticket_id: int) -> Optional[dict]:
    """Получить тикет."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM tickets WHERE ticket_id = $1", ticket_id)
    return dict(row) if row else None


async def get_ticket_messages(ticket_id: int, limit: int = 30) -> list[dict]:
    """Последние N сообщений тикета."""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT m.*, u.username
           FROM messages m
           LEFT JOIN users u ON u.tg_id = m.author_user_id
           WHERE m.ticket_id = $1
           ORDER BY m.created_at DESC
           LIMIT $2""",
        ticket_id, limit
    )
    return [dict(r) for r in reversed(rows)]


async def get_client_username(tg_id: int) -> str | None:
    """Получить username клиента."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT username FROM users WHERE tg_id = $1", tg_id)
    return row["username"] if row else None


async def get_all_users_with_start() -> list[int]:
    """Все tg_id пользователей, которые делали /start (для broadcast)."""
    pool = get_pool()
    rows = await pool.fetch("SELECT tg_id FROM users")
    return [r["tg_id"] for r in rows]


async def set_role(tg_id: int, role: str) -> None:
    """Установить роль (admin только). Создаёт пользователя, если нет."""
    pool = get_pool()
    await pool.execute(
        """INSERT INTO users (tg_id, role) VALUES ($1, $2)
           ON CONFLICT (tg_id) DO UPDATE SET role = EXCLUDED.role""",
        tg_id, role
    )

async def get_active_ticket_by_client(tg_id: int) -> Optional[dict]:
    """Активный тикет клиента."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT *
        FROM tickets
        WHERE client_user_id = $1
          AND status IN ('OPEN', 'WAITING')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        tg_id
    )
    return dict(row) if row else None

async def get_tickets_by_status(status: str) -> list[dict]:
    """
    Получить список тикетов по статусу OPEN или WAITING
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT
            t.ticket_id,
            t.status,
            t.client_user_id,
            t.assigned_to_support_id,
            uc.username AS client_username,
            us.username AS support_username
        FROM tickets t
        LEFT JOIN users uc ON uc.tg_id = t.client_user_id
        LEFT JOIN users us ON us.tg_id = t.assigned_to_support_id
        WHERE t.status = $1
        ORDER BY t.created_at ASC
        """,
        status
    )
    return [dict(r) for r in rows]

async def get_support_active_tickets(support_tg_id: int) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT *
        FROM tickets
        WHERE assigned_to_support_id = $1
          AND status IN ('WAITING')
        ORDER BY taken_at ASC
        """,
        support_tg_id
    )
    return [dict(r) for r in rows]

async def set_client_type(tg_id: int, client_type: ClientType) -> None:
    """Обновить client_type пользователя: NEW → EXISTING."""
    # if isinstance(client_type, ClientType):
    #     raise ValueError("client_type должен быть объектом ClientType, а не строкой")
    pool = get_pool()
    await pool.execute(
        "UPDATE users SET client_type = $1 WHERE tg_id = $2",
        client_type.value, tg_id
    )

async def get_leads_count(date_from: datetime, date_to: datetime):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS total
            FROM tickets
            WHERE created_at BETWEEN $1 AND $2
        """, date_from, date_to)

    return row["total"] if row else 0

async def get_avg_first_reply_time(date_from, date_to):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT AVG(EXTRACT(EPOCH FROM (first_reply_at - created_at))) AS avg_seconds
            FROM tickets
            WHERE first_reply_at IS NOT NULL
              AND created_at BETWEEN $1 AND $2
        """, date_from, date_to)

    if not row or not row["avg_seconds"]:
        return None

    return int(row["avg_seconds"])

async def get_sla_violations(date_from, date_to):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS violations
            FROM tickets
            WHERE first_reply_at IS NOT NULL
              AND created_at BETWEEN $1 AND $2
              AND (first_reply_at - created_at) > ($3 || ' minutes')::interval
        """, date_from, date_to, str(config.sla_minutes))

    return row["violations"] if row else 0

async def get_avg_messages_before_reply(date_from, date_to) -> Optional[float]:
    """
    Среднее количество сообщений от клиента (IN) до первого ответа саппорта (OUT)
    для тикетов, созданных между date_from и date_to.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
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
                GROUP BY t.ticket_id
            ) sub
        """, date_from, date_to)

    return float(row["avg_messages"]) if row and row["avg_messages"] else None


async def get_tickets_for_sla_check():
    """
    Получить тикеты, которые ещё не получили первый ответ (для SLA проверки).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM tickets
            WHERE first_reply_at IS NULL
              AND status IN ('OPEN', 'WAITING')
        """)
    return [dict(r) for r in rows]


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


async def get_lead_by_client_tg_id(client_tg_id: int) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM leads WHERE tg_id = $1",
        client_tg_id
    )

    return dict(row) if row else None
