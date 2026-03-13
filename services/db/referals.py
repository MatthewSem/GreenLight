"""Операции с БД."""
from typing import Optional
from config import config
import random
import string
from database import get_pool

async def get_or_create_referral(owner_client_id: int, created_by: int | None = None) -> dict:
    """
    Получить существующую или создать новую реферальную ссылку для клиента.
    created_by = tg_id того, кто создаёт ссылку (может быть клиент сам или админ/саппорт)
    Возвращает словарь: {"code": str, "link": str}
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Сначала ищем существующую
        row = await conn.fetchrow("""
            SELECT code FROM referrals
            WHERE owner_client_id = $1
            ORDER BY created_at ASC
            LIMIT 1
        """, owner_client_id)
        if row:
            code = row["code"]
            return {"code": code, "link": f"https://t.me/{config.bot_username}?start={code}"}

        # Генерируем уникальный код
        while True:
            code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            exists = await conn.fetchrow("SELECT 1 FROM referrals WHERE code = $1", code)
            if not exists:
                break

        # Если created_by не указан, значит создаём сами
        if created_by is None:
            created_by = owner_client_id

        # Сохраняем новую ссылку
        await conn.execute("""
            INSERT INTO referrals(owner_client_id, created_by, code)
            VALUES ($1, $2, $3)
        """, owner_client_id, created_by, code)

        return {"code": code, "link": f"https://t.me/{config.bot_username}?start={code}"}

async def get_user_id_by_username_referals(username: str) -> int | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT tg_id
        FROM users
        WHERE username = $1
        LIMIT 1
        """,
        username,
    )
    return row["tg_id"] if row else None

async def get_referral_by_code(code: str) -> Optional[dict]:
    """
    Найти реферальную ссылку по коду.
    Возвращает словарь с полями: referral_id, owner_client_id, created_by, code, owner_username
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT r.referral_id,
                   r.owner_client_id,
                   r.created_by,
                   r.code,
                   u.username AS owner_username
            FROM referrals r
            JOIN users u ON u.tg_id = r.owner_client_id
            WHERE r.code = $1
        """, code)
        if row:
            return dict(row)
    return None

async def create_referral_usage(referral_id: int, visitor_client_id: int, converted: bool = False) -> None:
    """
    Сохраняет факт перехода по реферальной ссылке.
    converted = True, если посетитель зарегистрировался
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO referral_usage(referral_id, visitor_client_id, visited_at, converted)
            VALUES ($1, $2, NOW(), $3)
        """, referral_id, visitor_client_id, converted)


# Version

async def get_keyboard_version(tg_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT keyboard_version
            FROM users
            WHERE tg_id = $1
            """,
            tg_id
        )

        if not row:
            return 0

        return row["keyboard_version"]

async def set_keyboard_version(tg_id: int, version: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET keyboard_version = $1
            WHERE tg_id = $2
            """,
            version,
            tg_id
        )