"""Операции с БД."""
from typing import Optional
from database import get_pool
from constants import ClientType


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

