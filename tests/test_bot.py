import pytest
import json
from database import get_pool


from services.db import (
    get_or_create_user,
    save_onboarding_answer,
    complete_onboarding,
    get_or_create_active_ticket,
    add_message, get_user_client_type, start_onboarding, transfer_onboarding_to_operator, set_role,
    take_ticket, get_support_active_tickets, update_ticket_status, get_ticket_messages, get_tickets_for_escalation,
)

from constants import ClientType

@pytest.mark.asyncio
async def test_user_creation_and_client_type(clean_db):
    pool = clean_db
    tg_id = 123456

    # Создаём пользователя
    user, client_type, is_paid = await get_or_create_user(tg_id, username="testuser")
    assert user["tg_id"] == tg_id
    assert client_type == ClientType.NEW

    # Проверяем тип клиента
    client_type_str = await get_user_client_type(tg_id)
    assert client_type_str == "new"

@pytest.mark.asyncio
async def test_onboarding_flow(clean_db):
    pool = clean_db
    tg_id = 123456

    # Старт онбординга
    await start_onboarding(tg_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM onboarding_state WHERE tg_id = $1", tg_id)
        assert row is not None
        assert row["current_step"] == 1

    # Сохраняем ответы
    await save_onboarding_answer(tg_id, 1, {"q1": "answer1"})
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT answers FROM onboarding_state WHERE tg_id = $1", tg_id)
        answers = row["answers"]
        if isinstance(answers, str):
            answers = json.loads(answers)
        assert answers["1"] == {"q1": "answer1"}

@pytest.mark.asyncio
async def test_complete_onboarding_creates_lead(clean_db):
    tg_id = 123456
    answers = {"1": "a1", "2": "a2"}

    # Завершаем онбординг
    lead_id = await complete_onboarding(tg_id, answers)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)
        assert row is not None
        assert row["tg_id"] == tg_id
        assert json.loads(row["answers"]) == answers

@pytest.mark.asyncio
async def test_active_ticket_creation(clean_db):
    tg_id = 123456
    ticket_id, is_new = await get_or_create_active_ticket(tg_id)
    assert is_new is True
    # Попытка получить снова — должен вернуться тот же тикет
    ticket_id2, is_new2 = await get_or_create_active_ticket(tg_id)
    assert ticket_id == ticket_id2
    assert is_new2 is False

@pytest.mark.asyncio
async def test_transfer_onboarding_to_operator(clean_db):
    tg_id = 123456
    # Старт и добавляем ответы
    await start_onboarding(tg_id)
    await save_onboarding_answer(tg_id, 1, {"q1": "answer1"})

    lead_id, ticket_id = await transfer_onboarding_to_operator(tg_id)
    assert lead_id is not None
    assert ticket_id is not None

    # Проверяем, что onboarding_state удалён
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM onboarding_state WHERE tg_id = $1", tg_id)
        assert row is None

@pytest.mark.asyncio
async def test_user_lifecycle(clean_db):
    tg_id = 1001
    support_id = 2001

    # 1️⃣ Создание пользователя
    user, client_type, is_turd = await get_or_create_user(tg_id, username="client1")
    assert user["tg_id"] == tg_id
    assert client_type == ClientType.NEW

    # 2️⃣ Старт онбординга
    await start_onboarding(tg_id)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM onboarding_state WHERE tg_id = $1", tg_id)
        assert row["current_step"] == 1

    # 3️⃣ Сохраняем несколько ответов
    await save_onboarding_answer(tg_id, 1, "answer1")
    await save_onboarding_answer(tg_id, 2, "answer2")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT answers FROM onboarding_state WHERE tg_id = $1", tg_id)
        answers = row["answers"]
        if isinstance(answers, str):
            answers = json.loads(answers)
        assert answers["1"] == "answer1"
        assert answers["2"] == "answer2"

    # 4️⃣ Завершаем онбординг
    lead_id = await complete_onboarding(tg_id, answers)
    assert lead_id is not None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)
        assert row["tg_id"] == tg_id
        assert json.loads(row["answers"]) == answers

    # 5️⃣ Создаём активный тикет
    ticket_id, is_new = await get_or_create_active_ticket(tg_id)
    assert is_new is True
    ticket_id2, is_new2 = await get_or_create_active_ticket(tg_id)
    assert ticket_id == ticket_id2
    assert is_new2 is False

    # 6️⃣ Добавляем сообщения в тикет
    await add_message(ticket_id, "IN", tg_id, text="Привет")
    await add_message(ticket_id, "OUT", support_id, text="Здравствуйте")
    messages = await get_ticket_messages(ticket_id)
    assert len(messages) == 2
    assert messages[0]["text"] == "Привет"
    assert messages[1]["text"] == "Здравствуйте"

    # 7️⃣ Присваиваем тикет оператору
    taken = await take_ticket(ticket_id, support_id)
    assert taken is True
    # Попытка взять снова — False
    taken_again = await take_ticket(ticket_id, support_id)
    assert taken_again is False

    # 8️⃣ Обновление статуса тикета
    await update_ticket_status(ticket_id, "CLOSED")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT status, closed_at FROM tickets WHERE ticket_id = $1", ticket_id)
        assert row["status"] == "CLOSED"
        assert row["closed_at"] is not None

@pytest.mark.asyncio
async def test_role_management(clean_db):
    tg_id = 3001

    # 1️⃣ Установка роли
    await set_role(tg_id, "admin")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT role FROM users WHERE tg_id = $1", tg_id)
        assert row["role"] == "admin"

    # 2️⃣ Обновление роли
    await set_role(tg_id, "support")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT role FROM users WHERE tg_id = $1", tg_id)
        assert row["role"] == "support"

@pytest.mark.asyncio
async def test_support_ticket_list(clean_db):
    client1 = 4001
    client2 = 4002
    support = 5001

    # Создаём пользователей и тикеты
    for cid in [client1, client2]:
        await get_or_create_user(cid)
        tid, _ = await get_or_create_active_ticket(cid)
        await take_ticket(tid, support)

    # Проверяем список активных тикетов у оператора
    tickets = await get_support_active_tickets(support)
    assert len(tickets) == 2
    ticket_client_ids = {t["client_user_id"] for t in tickets}
    assert ticket_client_ids == {client1, client2}

@pytest.mark.asyncio
async def test_onboarding_without_start(clean_db):
    tg_id = 9001

    # Попытка сохранить ответ без старта онбординга
    with pytest.raises(Exception):
        await save_onboarding_answer(tg_id, 1, "answer")

    # Завершение онбординга без старта
    lead_id = await complete_onboarding(tg_id, {"1": "answer"})
    assert lead_id is not None
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)
        assert row["tg_id"] == tg_id

@pytest.mark.asyncio
async def test_ticket_for_nonexistent_user(clean_db):
    tg_id = 9999

    # Создание тикета для пользователя, которого нет в users
    ticket_id, is_new = await get_or_create_active_ticket(tg_id)
    assert is_new is True
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tickets WHERE ticket_id = $1", ticket_id)
        assert row["client_user_id"] == tg_id

@pytest.mark.asyncio
async def test_duplicate_messages(clean_db):
    tg_id = 9100
    support_id = 9200

    # Создаём пользователя и тикет
    await get_or_create_user(tg_id)
    ticket_id, _ = await get_or_create_active_ticket(tg_id)

    # Добавляем одинаковые сообщения
    await add_message(ticket_id, "IN", tg_id, text="Hello")
    await add_message(ticket_id, "IN", tg_id, text="Hello")
    messages = await get_ticket_messages(ticket_id)
    texts = [m["text"] for m in messages]
    assert texts.count("Hello") == 2

@pytest.mark.asyncio
async def test_take_ticket_already_taken(clean_db):
    tg_id = 9201
    support1 = 9301
    support2 = 9302

    await get_or_create_user(tg_id)
    ticket_id, _ = await get_or_create_active_ticket(tg_id)

    taken1 = await take_ticket(ticket_id, support1)
    assert taken1 is True

    # Другой оператор не может взять
    taken2 = await take_ticket(ticket_id, support2)
    assert taken2 is False

@pytest.mark.asyncio
async def test_update_ticket_status_invalid(clean_db):
    tg_id = 9401
    await get_or_create_user(tg_id)
    ticket_id, _ = await get_or_create_active_ticket(tg_id)

    # Передаём некорректный статус
    with pytest.raises(Exception):
        await update_ticket_status(ticket_id, "INVALID_STATUS")

@pytest.mark.asyncio
async def test_escalation_logic(clean_db):
    tg_id = 9501
    support = 9601

    await get_or_create_user(tg_id)
    ticket_id, _ = await get_or_create_active_ticket(tg_id)
    await take_ticket(ticket_id, support)

    # Имитируем тикет, который ждёт >30 минут
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE tickets SET taken_at = NOW() - INTERVAL '31 minutes', status = 'WAITING' WHERE ticket_id = $1",
            ticket_id
        )


    tickets = await get_tickets_for_escalation()
    ticket_ids = [t["ticket_id"] for t in tickets]
    assert ticket_id in ticket_ids