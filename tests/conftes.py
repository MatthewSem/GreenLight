import pytest
import asyncpg

TEST_DB_URL = "postgresql://postgres:Returntypbg@localhost:5432/greenlight"

@pytest.fixture(scope="session")
async def db_pool():
    # Подключаемся к тестовой БД
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        # Очистим таблицы перед тестами
        await conn.execute("TRUNCATE users CASCADE")
        await conn.execute("TRUNCATE onboarding_state CASCADE")
        await conn.execute("TRUNCATE tickets CASCADE")
        await conn.execute("TRUNCATE leads CASCADE")
        await conn.execute("TRUNCATE messages CASCADE")
    yield pool
    await pool.close()


import pytest_asyncio
import asyncpg
from database import Database  # твой класс Database

TEST_DB_URL = "postgresql://postgres:Returntypbg@localhost:5432/greenlight"


@pytest_asyncio.fixture
async def clean_db():
    """
    Подключаем тестовую БД и очищаем её перед каждым тестом.
    Также подменяем Database.pool, чтобы get_pool() работал.
    """

    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=5)

    # 👇 ВАЖНО: подменяем пул в твоём Database
    Database.pool = pool

    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE users CASCADE")
        await conn.execute("TRUNCATE onboarding_state CASCADE")
        await conn.execute("TRUNCATE leads CASCADE")
        await conn.execute("TRUNCATE tickets CASCADE")
        await conn.execute("TRUNCATE messages CASCADE")

    yield pool

    await pool.close()
    Database.pool = None
