"""Подключение к PostgreSQL и работа с БД."""
import asyncpg
from typing import Optional

from config import config


class Database:
    """Пул подключений к PostgreSQL."""

    pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def connect(cls) -> None:
        """Создать пул подключений."""
        cls.pool = await asyncpg.create_pool(
            config.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        await cls._init_tables()

    @classmethod
    async def disconnect(cls) -> None:
        """Закрыть пул."""
        if cls.pool:
            await cls.pool.close()
            cls.pool = None

    @classmethod
    async def _init_tables(cls) -> None:
        """Создание таблиц при старте."""
        async with cls.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id BIGINT PRIMARY KEY,
                    username TEXT,
                    role TEXT NOT NULL DEFAULT 'client',
                    client_type TEXT NOT NULL DEFAULT 'new',
                    is_blocked BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW() ,
                    last_seen TIMESTAMPTZ DEFAULT NOW(),
                    onboarding_completed_at TIMESTAMPTZ,
                    onboarding_step INTEGER DEFAULT 0,
                    is_paid BOOLEAN DEFAULT FALSE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id SERIAL PRIMARY KEY,
                    tg_id BIGINT NOT NULL REFERENCES users(tg_id),
                    answers JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    status TEXT NOT NULL DEFAULT 'NEW_LEAD'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id SERIAL PRIMARY KEY,
                    client_user_id BIGINT NOT NULL REFERENCES users(tg_id),
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    assigned_to_support_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    taken_at TIMESTAMPTZ,
                    first_reply_at TIMESTAMPTZ,
                    closed_at TIMESTAMPTZ,
                    sla_stage SMALLINT DEFAULT 0,
                    support_thread_id BIGINT,
                    ticket_card_message_id BIGINT,
                    ticket_topic_card_message_id BIGINT
                )
            """)
            # Миграция: добавить колонки, если таблица уже существовала
            try:
                await conn.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS support_thread_id BIGINT"
                )
                await conn.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_card_message_id BIGINT"
                )
                await conn.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_topic_card_message_id BIGINT"
                )
                await conn.execute(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE"
                )
                await conn.execute(
                    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_stage SMALLINT DEFAULT 0"
                )
            except Exception:
                pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id SERIAL PRIMARY KEY,
                    ticket_id INTEGER REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    direction TEXT NOT NULL,
                    author_user_id BIGINT,
                    text TEXT,
                    media_type TEXT,
                    media_file_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS onboarding_state (
                    tg_id BIGINT PRIMARY KEY REFERENCES users(tg_id),
                    current_step INTEGER DEFAULT 1,
                    answers JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)


def get_pool() -> asyncpg.Pool:
    """Получить пул подключений."""
    if Database.pool is None:
        raise RuntimeError("Database not connected. Call Database.connect() first.")
    return Database.pool
