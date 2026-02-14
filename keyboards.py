"""Клавиатуры бота."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


# --- Онбординг ---
def onboarding_transfer_kb() -> InlineKeyboardMarkup:
    """Кнопка «Передать оператору» во время онбординга."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💼 Передать оператору", callback_data="onboarding:transfer")]
    ])


# --- Тикет (Support Group) ---
def ticket_kb(
    ticket_id: int,
    is_taken: bool = False,
    status: str = "OPEN",
) -> InlineKeyboardMarkup:
    """Кнопки управления тикетом. При CLOSED — только История и Статус."""
    buttons = []
    if status == "CLOSED":
        buttons.extend([
            [
                InlineKeyboardButton(text="📜 История", callback_data=f"ticket:history:{ticket_id}"),
                InlineKeyboardButton(text="🟡 Статус", callback_data=f"ticket:status:{ticket_id}"),
            ],
        ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    if not is_taken:
        buttons.append([InlineKeyboardButton(text="✅ Взять", callback_data=f"ticket:take:{ticket_id}")])
    buttons.extend([
        [InlineKeyboardButton(text="✉️ Ответить", callback_data=f"ticket:reply:{ticket_id}")],
        [
            InlineKeyboardButton(text="📜 История", callback_data=f"ticket:history:{ticket_id}"),
            InlineKeyboardButton(text="🟡 Статус", callback_data=f"ticket:status:{ticket_id}"),
        ],
        [InlineKeyboardButton(text="💰 Оплатил", callback_data=f"ticket:paid:{ticket_id}",)],
        [InlineKeyboardButton(text="⛔ Эскалация", callback_data=f"ticket:escalate:{ticket_id}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ticket_status_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Выбор статуса тикета."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="OPEN", callback_data=f"status:OPEN:{ticket_id}")],
        [InlineKeyboardButton(text="WAITING", callback_data=f"status:WAITING:{ticket_id}")],
        [InlineKeyboardButton(text="CLOSED", callback_data=f"status:CLOSED:{ticket_id}")],
    ])


# --- Broadcast ---
def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение рассылки кнопкой."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast:confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel")],
    ])
