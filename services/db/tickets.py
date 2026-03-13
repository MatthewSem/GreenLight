"""Операции с БД."""
from typing import Optional, Tuple, List
import json
import datetime
from config import config

from database import get_pool
from constants import ClientType, TicketStatus
from services.db.users import get_or_create_user


async def get_or_create_active_ticket(client_tg_id: int) -> tuple[int, bool]:
    """
    Получить активный тикет или создать новый.
    Возвращает (ticket_id, is_new).
    """
    await get_or_create_user(client_tg_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        open_ticket = await conn.fetchrow(
            """
                SELECT ticket_id FROM tickets
                WHERE client_user_id = $1 AND status IN ('DRAFT', 'OPEN', 'WAITING')
                ORDER BY created_at DESC
                LIMIT 1
            """,
            client_tg_id
        )
        if open_ticket:
            return open_ticket["ticket_id"], False

        ticket_id = await conn.fetchval(
            """INSERT INTO tickets (client_user_id, status) VALUES ($1, 'DRAFT')
               RETURNING ticket_id""",
            client_tg_id
        )
        return ticket_id, True

async def activate_ticket(ticket_id:int):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE tickets
            SET status = 'OPEN',
                sla_stage = 0
            WHERE ticket_id = $1
            """,
            ticket_id
        )

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

async def get_history_messages_full(client_tg_id: int) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                m.*,
                t.ticket_id,
                u.username
            FROM messages m
            JOIN tickets t ON t.ticket_id = m.ticket_id
            LEFT JOIN users u ON u.tg_id = m.author_user_id
            WHERE t.client_user_id = $1
            ORDER BY m.created_at ASC
            """,
            client_tg_id
        )
    return [dict(r) for r in rows]

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

async def get_all_supports() -> list[dict]:
    """
    Возвращает список всех саппортов с tg_id и username
    """
    pool = await get_pool()
    rows = await pool.fetch("SELECT tg_id, username FROM users WHERE role = 'support'")
    return [{"tg_id": r["tg_id"], "username": r["username"]} for r in rows]

async def set_role(tg_id: int, role: str) -> None:
    """Установить роль (admin только). Создаёт пользователя, если нет."""
    pool = get_pool()
    await pool.execute(
        """INSERT INTO users (tg_id, role) VALUES ($1, $2)
           ON CONFLICT (tg_id) DO UPDATE SET role = EXCLUDED.role""",
        tg_id, role
    )

# ----------------------
# Получить tg_id пользователя по username (только support/admin)
# ----------------------
async def get_user_id_by_username(username: str) -> int | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT tg_id
        FROM users
        WHERE username = $1
          AND role IN ('support', 'admin')
        LIMIT 1
        """,
        username,
    )
    return row["tg_id"] if row else None

# ----------------------
# Получить все открытые тикеты саппорта
# ----------------------
async def get_open_tickets_by_support(support_id: int) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT *
        FROM tickets
        WHERE assigned_to_support_id = $1
          AND status != 'CLOSED'
        """,
        support_id,
    )
    return [dict(r) for r in rows]

# ----------------------
# Передать тикет другому саппорту
# ----------------------
async def transfer_ticket(ticket_id: int, new_support_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE tickets
        SET assigned_to_support_id = $1
        WHERE ticket_id = $2
        """,
        new_support_id, ticket_id,
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


async def upsert_user_with_client_type(
    tg_id: int,
    username: str | None,
    client_type: ClientType
) -> None:
    pool = get_pool()

    await pool.execute("""
        INSERT INTO users (tg_id, username, client_type)
        VALUES ($1, $2, $3)
        ON CONFLICT (tg_id)
        DO UPDATE SET
            client_type = EXCLUDED.client_type,
            username = COALESCE(EXCLUDED.username, users.username)
    """, tg_id, username, client_type.value)


async def get_lead_by_client_tg_id(client_tg_id: int) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM leads WHERE tg_id = $1",
        client_tg_id
    )

    return dict(row) if row else None

async def mark_user_active(tg_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
            SET first_message_at = COALESCE(first_message_at, NOW())
            WHERE tg_id = $1
        """, tg_id)


async def update_created_at_for_draft_on_open(ticket_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE tickets
            SET created_at = NOW()
            WHERE ticket_id = $1
        """, ticket_id)
