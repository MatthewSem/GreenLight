"""Операции с БД."""
from typing import Optional
import json
from database import get_pool
from constants import ClientType
from services.db.users import get_or_create_user


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