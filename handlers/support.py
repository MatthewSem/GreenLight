"""Обработчики для Support Group — кнопки тикетов."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from constants import MSG_REPLY_PROMPT, ClientType
from services.db import (
    get_user_role,
    get_ticket,
    take_ticket,
    add_message,
    set_first_reply_if_needed,
    get_ticket_messages,
    update_ticket_status,
    get_client_username,
    get_user_client_type,
    set_ticket_thread_id,
    set_ticket_topic_card_message_id,
    get_support_active_tickets,
)
from services.support_chat import (
    send_escalation_to_admin,
    send_ticket_to_support_group,
    refresh_ticket_card,
)
from keyboards import ticket_kb, ticket_status_kb
from config import config

router = Router(name="support")

# Хранилище ожидаемых ответов: {support_tg_id: ticket_id}
pending_replies: dict[int, int] = {}

def _is_support(tg_id: int) -> bool:
    """Проверка роли — sync, для filter. Роль проверяется в хендлере асинхронно."""
    return True  # Проверка в хендлере


async def _check_support(callback: CallbackQuery) -> bool:
    """Проверить, что пользователь — support или admin."""
    role = await get_user_role(callback.from_user.id, config.admin_ids or [])
    return role in ("support", "admin")

@router.message(F.chat.type == "private", F.text == "/my_tickets")
async def my_tickets(message: Message):
    role = await get_user_role(message.from_user.id, config.admin_ids or [])
    if role not in ("support", "admin"):
        await message.answer("Команда доступна только поддержке.")
        return

    tickets = await get_support_active_tickets(message.from_user.id)
    if not tickets:
        await message.answer("У вас нет активных тикетов.")
        return

    lines = []
    for t in tickets:
        lines.append(
            f"🎫 Ticket #{t['ticket_id']}\n"
            f"Статус: {t['status']}\n"
            f"/go_{t['ticket_id']}"
        )

    await message.answer("\n\n".join(lines))

@router.message(F.text.startswith("/go_"))
async def go_ticket(message: Message):
    try:
        ticket_id = int(message.text.replace("/go_", ""))
    except ValueError:
        return

    ticket = await get_ticket(ticket_id)

    if not ticket or ticket["assigned_to_support_id"] != message.from_user.id:
        await message.answer("⛔ Тикет не найден или не ваш.")
        return

    thread_id = ticket.get("support_thread_id")
    msg_id = ticket.get("ticket_topic_card_message_id")

    if not thread_id or not msg_id:
        await message.answer("❌ У тикета нет темы.")
        return

    internal_id = str(abs(config.support_group_id)).replace("100", "", 1)
    link = f"https://t.me/c/{internal_id}/{msg_id}"

    await message.answer(
        f"➡️ <b>Тикет #{ticket_id}</b>\n"
        f"Перейти в чат поддержки:\n"
        f"<a href=\"{link}\">Открыть тему</a>",
        disable_web_page_preview=True,
    )

    await message.bot.send_message(
        config.support_group_id,
        f"👤 Оператор @{message.from_user.username or message.from_user.id} открыл тикет",
        message_thread_id=thread_id,
    )




@router.callback_query(F.data.startswith("ticket:"))
async def ticket_callback(cb: CallbackQuery):
    """Обработка кнопок тикета."""
    if cb.message.chat.id != config.support_group_id:
        return

    if not await _check_support(cb):
        await cb.answer("Доступ запрещён", show_alert=True)
        return

    data = cb.data
    parts = data.split(":")
    if len(parts) < 3:
        return

    action = parts[1]
    try:
        ticket_id = int(parts[2])
    except ValueError:
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        await cb.answer("Тикет не найден", show_alert=True)
        return

    assigned_id = ticket.get("assigned_to_support_id")
    status = ticket.get("status") or "OPEN"
    is_assignee = assigned_id is not None and assigned_id == cb.from_user.id

    # Только назначенный оператор может что-либо делать с тикетом (кроме «Взять»)
    if action != "take" and assigned_id is not None and not is_assignee:
        assignee_username = await get_client_username(assigned_id) or "—"
        await cb.answer(
            f"Тикет ведёт другой оператор (@{assignee_username}). Действия недоступны.",
            show_alert=True,
        )
        return

    if action == "reply":
        if status == "CLOSED":
            await cb.answer(
                "Тикет закрыт. Доступны только «История» и «Статус» (можно открыть заново).",
                show_alert=True,
            )
            return
        if status == "OPEN":
            await cb.answer(
                "Сначала возьмите тикет кнопкой «Взять» — только после этого можно отвечать клиенту.",
                show_alert=True,
            )
            return
        pending_replies[cb.from_user.id] = ticket_id
        await cb.answer("Режим ответа включён — все сообщения в этой теме пойдут клиенту. Нажмите другую кнопку, чтобы выйти.")
        await cb.message.answer(MSG_REPLY_PROMPT)
        return

    # Любая другая кнопка — выходим из режима ответа
    pending_replies.pop(cb.from_user.id, None)

    if action == "escalate":
        if status == "CLOSED":
            await cb.answer("Эскалация недоступна для закрытого тикета.", show_alert=True)
            return
        client_tg_id = ticket["client_user_id"]
        client_username = await get_client_username(client_tg_id) or "—"
        support_username = cb.from_user.username or "—"
        last_msg = "(нет сообщений)"
        msgs = await get_ticket_messages(ticket_id, limit=1)
        if msgs:
            last_msg = msgs[-1].get("text") or "(медиа)"
        await send_escalation_to_admin(
            cb.message.bot,
            ticket_id=ticket_id,
            support_username=support_username,
            client_username=client_username,
            last_message=last_msg,
            status=ticket["status"],
        )
        await cb.answer("Эскалация отправлена")
        return

    if action == "take":
        ok = await take_ticket(ticket_id, cb.from_user.id)
        if not ok:
            await cb.answer("Тикет уже взят", show_alert=True)
            return

        await cb.answer("Тикет взят — переносим в вашу тему…")

        # Создать тему (форум-топик) и перенести тикет туда
        try:
            topic = await cb.message.bot.create_forum_topic(
                chat_id=config.support_group_id,
                name=f"Ticket #{ticket_id}",
            )
            thread_id = topic.message_thread_id
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Не удалось создать тему для тикета #%s (включите «Темы» в настройках группы): %s",
                ticket_id, e,
            )
            # Fallback: тикет взят, переводим в WAITING и обновляем карточку в общем чате
            await update_ticket_status(ticket_id, "WAITING")
            await refresh_ticket_card(cb.message.bot, ticket_id)
            return

        # Отправить карточку тикета в тему (обновлённый тикет уже с taken_at)
        ticket = await get_ticket(ticket_id)
        client_tg_id = ticket["client_user_id"]
        username = await get_client_username(client_tg_id) or "—"
        ct = await get_user_client_type(client_tg_id)
        client_type_label = "🆕 Новый" if ct == "new" else "👤 Действующий"
        taken_str = datetime.now().strftime("%H:%M")
        last_msg = "(тикет взят)"
        msgs = await get_ticket_messages(ticket_id, limit=1)
        if msgs:
            last_msg = msgs[-1].get("text") or "(медиа)"

        card_msg_id = await send_ticket_to_support_group(
            bot=cb.message.bot,
            ticket_id=ticket_id,
            client_tg_id=client_tg_id,
            username=username,
            client_type_label=client_type_label,
            last_message=last_msg,
            message_thread_id=thread_id,
        )
        await set_ticket_thread_id(ticket_id, thread_id)
        if card_msg_id:
            await set_ticket_topic_card_message_id(ticket_id, card_msg_id)

        # OPEN → WAITING только после того, как оператор взял тикет (теперь можно писать клиенту)
        await update_ticket_status(ticket_id, "WAITING")
        await refresh_ticket_card(cb.message.bot, ticket_id)

        # Удалить карточку из общего чата
        card_msg_id = ticket.get("ticket_card_message_id")
        if card_msg_id:
            try:
                await cb.message.bot.delete_message(
                    config.support_group_id,
                    card_msg_id,
                )
            except Exception:
                pass

    elif action == "history":
        messages = await get_ticket_messages(ticket_id, limit=30)
        if not messages:
            await cb.answer("История пуста")
            return

        def _media_label(m: dict) -> str:
            mt = m.get("media_type")
            if not mt:
                return ""
            labels = {"photo": "📷 фото", "voice": "🎤 голосовое", "document": "📎 документ", "video": "🎬 видео", "audio": "🎵 аудио"}
            return " " + labels.get(mt, mt)

        lines = []
        for m in messages:
            ts = m["created_at"]
            if hasattr(ts, "strftime"):
                ts_str = ts.strftime("%H:%M")
            else:
                ts_str = str(ts)[:5]
            direction = m["direction"]
            author = m.get("username") or "—"
            text = (m.get("text") or "").strip()
            if not text and m.get("media_type"):
                text = "(медиа)"
            elif not text:
                text = "(медиа)"
            text = (text + _media_label(m)).strip()[:100]
            if direction == "IN":
                lines.append(f"[{ts_str}] CLIENT: {text}")
            else:
                lines.append(f"[{ts_str}] SUPPORT(@{author}): {text}")

        history_text = "\n".join(lines[-30:])
        if len(history_text) > 4000:
            history_text = history_text[-4000:]
        await cb.answer()
        thread_id = getattr(cb.message, "message_thread_id", None)
        # answer() сам подставляет message_thread_id из контекста — не передаём его явно
        await cb.message.answer(text=f"📜 История тикета #{ticket_id}:\n\n{history_text}")

        # Отправляем медиа для просмотра (последние 10 с фото/голосом/документом/видео/аудио)
        media_kw = {"message_thread_id": thread_id} if thread_id else {}
        media_sent = 0
        for m in reversed(messages):
            if media_sent >= 10:
                break
            mt, fid = m.get("media_type"), m.get("media_file_id")
            if not fid or not mt:
                continue
            ts = m["created_at"]
            ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[:5]
            who = "CLIENT" if m["direction"] == "IN" else "SUPPORT"
            cap = f"[{ts_str}] {who}"
            try:
                if mt == "photo":
                    await cb.message.bot.send_photo(config.support_group_id, fid, caption=cap, **media_kw)
                elif mt == "voice":
                    await cb.message.bot.send_voice(config.support_group_id, fid, caption=cap, **media_kw)
                elif mt == "document":
                    await cb.message.bot.send_document(config.support_group_id, fid, caption=cap, **media_kw)
                elif mt == "video":
                    await cb.message.bot.send_video(config.support_group_id, fid, caption=cap, **media_kw)
                elif mt == "audio":
                    await cb.message.bot.send_audio(config.support_group_id, fid, caption=cap, **media_kw)
                else:
                    continue
                media_sent += 1
            except Exception:
                pass
        if media_sent:
            await cb.message.answer(text=f"📎 Показано медиа: {media_sent}")

    elif action == "status":
        await cb.answer()
        await cb.message.answer(
            "Выберите статус:",
            reply_markup=ticket_status_kb(ticket_id),
        )

    elif action == "paid":
        if status != "WAITING":
            await cb.answer(
                "Оплата возможна только для тикета в работе (WAITING).",
                show_alert=True,
            )
            return

        if assigned_id != cb.from_user.id:
            await cb.answer(
                "Только назначенный оператор может подтвердить оплату.",
                show_alert=True,
            )
            return

        client_tg_id = ticket["client_user_id"]
        client_username = await get_client_username(client_tg_id)

        # 🔁 Отправка в CRM (перевод лида → клиент)
        from services.crm import send_client_to_crm

        ok = await send_client_to_crm(
            lead_id=ticket_id,
            tg_id=client_tg_id,
            username=client_username,
        )

        if not ok:
            await cb.answer(
                "❌ Не удалось отправить данные в CRM",
                show_alert=True,
            )
            return

        # 🏷 Меняем тип клиента
        from services.db import set_user_client_type
        await set_user_client_type(client_tg_id, ClientType.EXISTING)

        # 🔒 Закрываем тикет
        # await update_ticket_status(ticket_id, "CLOSED")
        await refresh_ticket_card(cb.message.bot, ticket_id)

        # 📩 Уведомления
        thread_id = ticket.get("support_thread_id")
        notify_kw = {}
        if thread_id:
            notify_kw["message_thread_id"] = thread_id

        await cb.message.bot.send_message(
            config.support_group_id,
            "💰 Оплата подтверждена. Клиент переведён в CRM как клиент.",
            **notify_kw,
        )

        try:
            await cb.message.bot.send_message(
                client_tg_id,
                "✅ Мы получили оплату, спасибо! С вами продолжит работать поддержка.",
            )
        except Exception:
            pass

        await cb.answer("Оплата подтверждена ✅")


@router.callback_query(F.data.startswith("status:"))
async def status_callback(cb: CallbackQuery):
    """Смена статуса тикета. Только назначенный оператор может менять статус."""
    if cb.message.chat.id != config.support_group_id:
        return
    if not await _check_support(cb):
        return

    parts = cb.data.split(":")
    if len(parts) != 3:
        return
    new_status = parts[1]
    try:
        ticket_id = int(parts[2])
    except ValueError:
        return

    if new_status not in ("OPEN", "WAITING", "CLOSED"):
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        await cb.answer("Тикет не найден", show_alert=True)
        return
    assigned_id = ticket.get("assigned_to_support_id")
    if assigned_id is not None and assigned_id != cb.from_user.id:
        await cb.answer("Тикет ведёт другой оператор. Сменить статус может только он.", show_alert=True)
        return

    old_status = ticket.get("status") or "OPEN"
    await update_ticket_status(ticket_id, new_status)
    logger.info(
        "Тикет #%s: статус изменён %s -> %s (оператор %s)",
        ticket_id, old_status, new_status, cb.from_user.id,
    )
    await refresh_ticket_card(cb.message.bot, ticket_id)
    await cb.answer(f"Статус: {new_status}")


@router.message(F.chat.id == config.support_group_id)
async def support_reply_message(message: Message):
    """
    Ответ оператора клиенту. Режим включается одной кнопкой «Ответить».
    Писать клиенту можно только когда тикет в статусе WAITING (взят оператором); при OPEN — нельзя.
    """
    tg_id = message.from_user.id
    ticket_id = pending_replies.get(tg_id)
    if not ticket_id:
        return

    role = await get_user_role(tg_id, config.admin_ids or [])
    if role not in ("support", "admin"):
        pending_replies.pop(tg_id, None)
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        pending_replies.pop(tg_id, None)
        return

    # Сообщение должно быть в той же теме, что и тикет (или оба в общем чате)
    msg_thread = getattr(message, "message_thread_id", None)
    ticket_thread = ticket.get("support_thread_id")
    if (msg_thread or None) != (ticket_thread or None):
        return

    thread_id = getattr(message, "message_thread_id", None)
    err_kw = lambda text: {"text": text, **({"message_thread_id": thread_id} if thread_id is not None else {})}

    if ticket.get("status") == "CLOSED":
        await message.bot.send_message(config.support_group_id, **err_kw("Тикет закрыт. Ответы клиенту недоступны."))
        return

    # Пока тикет OPEN — никто не может писать клиенту (тикет ещё не взят)
    if ticket.get("status") == "OPEN":
        await message.bot.send_message(
            config.support_group_id,
            **err_kw("Сначала возьмите тикет кнопкой «Взять» — только после этого можно отвечать клиенту."),
        )
        return

    assigned_id = ticket.get("assigned_to_support_id")
    if assigned_id is not None and assigned_id != tg_id:
        await message.bot.send_message(
            config.support_group_id,
            **err_kw("Этот тикет ведёт другой оператор. Вы не можете отвечать от его имени."),
        )
        return

    client_tg_id = ticket["client_user_id"]
    text = message.text or message.caption or ""

    media_type = None
    media_file_id = None
    if message.photo:
        media_type, media_file_id = "photo", message.photo[-1].file_id
    elif message.document:
        media_type, media_file_id = "document", message.document.file_id
    elif message.video:
        media_type, media_file_id = "video", message.video.file_id
    elif message.voice:
        media_type, media_file_id = "voice", message.voice.file_id
    elif message.audio:
        media_type, media_file_id = "audio", message.audio.file_id

    await add_message(
        ticket_id, "OUT", tg_id,
        text=text or "(медиа)",
        media_type=media_type,
        media_file_id=media_file_id,
    )
    await set_first_reply_if_needed(ticket_id)

    thread_id = getattr(message, "message_thread_id", None)
    confirm_kw = {"text": "✅ Ответ отправлен клиенту"}
    if thread_id is not None:
        confirm_kw["message_thread_id"] = thread_id

    # Отправка клиенту в личку бота (chat_id = user id)
    try:
        bot = message.bot
        if media_type == "photo":
            await bot.send_photo(chat_id=client_tg_id, photo=media_file_id, caption=text or None)
        elif media_type == "document":
            await bot.send_document(chat_id=client_tg_id, document=media_file_id, caption=text or None)
        elif media_type == "video":
            await bot.send_video(chat_id=client_tg_id, video=media_file_id, caption=text or None)
        elif media_type == "voice":
            await bot.send_voice(chat_id=client_tg_id, voice=media_file_id, caption=text or None)
        elif media_type == "audio":
            await bot.send_audio(chat_id=client_tg_id, audio=media_file_id, caption=text or None)
        else:
            await bot.send_message(chat_id=client_tg_id, text=text or "(медиа)")
        await bot.send_message(chat_id=config.support_group_id, **confirm_kw)
    except Exception as e:
        logger.warning(
            "Не удалось отправить ответ клиенту chat_id=%s (ticket #%s): %s",
            client_tg_id, ticket_id, e,
        )
        err_kw = {"text": "Не удалось отправить клиенту (возможно, заблокировал бота). Проверьте логи."}
        if thread_id is not None:
            err_kw["message_thread_id"] = thread_id
        await message.bot.send_message(chat_id=config.support_group_id, **err_kw)
