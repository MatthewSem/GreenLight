"""Отправка данных в CRM: webhook и Google Sheets."""
import asyncio
import json
from datetime import datetime

import aiohttp
from config import config


async def send_lead_to_crm(
    lead_id: int, tg_id: int, username: str | None, answers: dict
) -> bool:
    """Отправить карточку лида в CRM (webhook и/или Google Sheets)."""
    payload = {
        "lead_id": lead_id,
        "tg_id": tg_id,
        "username": username,
        "answers": answers,
        "client_type": "new",
        "status": "NEW_LEAD",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    ok_webhook = False
    if config.crm_enabled and config.crm_webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.crm_webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    ok_webhook = resp.status in (200, 201, 204)
        except Exception:
            pass

    ok_sheets = False
    if config.google_sheets_enabled and config.google_credentials_file and config.spreadsheet_id:
        ok_sheets = await _append_lead_to_sheets(lead_id, tg_id, username, answers)

    return ok_webhook or ok_sheets

async def send_client_to_crm(
    lead_id: int, tg_id: int, username: str | None
) -> bool:
    """Отправить карточку лида в CRM (webhook и/или Google Sheets)."""
    payload = {
        "lead_id": lead_id,
        "tg_id": tg_id,
        "username": username,
        "client_type": "Extension",
        "status": "Client",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    ok_webhook = False
    if config.crm_enabled and config.crm_webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.crm_webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    ok_webhook = resp.status in (200, 201, 204)
        except Exception:
            pass

    ok_sheets = False
    if config.google_sheets_enabled and config.google_credentials_file and config.spreadsheet_id:
        ok_sheets = await _append_client_to_sheets(lead_id, tg_id, username)

    return ok_webhook or ok_sheets

def _append_lead_to_sheets_sync(
    lead_id: int, tg_id: int, username: str | None, answers: dict
) -> bool:
    """Синхронная запись лида в Google Sheets."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            config.google_credentials_file, scopes=scopes
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(config.spreadsheet_id)
        sheet = sh.worksheet(config.sheet_name)

        # Заголовки ожидаются: lead_id, tg_id, username, created_at, status, answer_1..answer_9
        row = [
            lead_id,
            tg_id,
            username or "",
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "NEW_LEAD",
        ]
        for i in range(1, 10):
            val = answers.get(str(i))
            if isinstance(val, dict):
                text = (val.get("text") or "").strip()
                if not text and val.get("media_type"):
                    text = "(медиа)"
                row.append(text or "")
            else:
                row.append(str(val) if val is not None else "")

        sheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False

def _append_client_to_sheets_sync(
    lead_id: int, tg_id: int, username: str | None
) -> bool:
    """Синхронная запись лида в Google Sheets."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            config.google_credentials_file, scopes=scopes
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(config.spreadsheet_id)
        sheet = sh.worksheet(config.sheet_name_client)

        # Заголовки ожидаются: lead_id, tg_id, username, created_at, status, answer_1..answer_9
        row = [
            lead_id,
            tg_id,
            username or "",
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "Client",
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


async def _append_lead_to_sheets(
    lead_id: int, tg_id: int, username: str | None, answers: dict
) -> bool:
    """Асинхронная обёртка для записи в Google Sheets."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _append_lead_to_sheets_sync,
        lead_id,
        tg_id,
        username,
        answers,
    )

async def _append_client_to_sheets(
    lead_id: int, tg_id: int, username: str | None
) -> bool:
    """Асинхронная обёртка для записи в Google Sheets."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _append_client_to_sheets_sync,
        lead_id,
        tg_id,
        username,
    )
