"""Конфигурация приложения."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Настройки бота и окружения."""

    # Telegram
    bot_token: str = ""
    support_group_id: int = 0
    admin_chat_id: int = 0
    private_chat_id: int = 0

    # Database
    database_url: str = ""

    # CRM
    crm_webhook_url: str = ""
    crm_enabled: bool = False
    # Google Sheets CRM
    google_sheets_enabled: bool = False
    google_credentials_file: str = ""
    spreadsheet_id: str = ""
    sheet_name: str = "Лиды"
    sheet_name_client: str = "Клиенты"

    # Рабочее время (Europe/Moscow)
    timezone: str = "Europe/Moscow"
    work_start_hour: int = 10
    work_end_hour: int = 22
    sla_minutes: int = 30

    # SLA
    sla_warning_minutes: int = 15
    sla_admin_minutes: int = 30
    sla_critical_minutes: int = 120

    # Первичные админы (tg_id через запятую)
    admin_ids: list[int] | None = None

    @classmethod
    def load(cls) -> "Config":
        return cls(
            bot_token=os.getenv("BOT_TOKEN", ""),
            support_group_id=int(os.getenv("SUPPORT_GROUP_ID", "0")),
            admin_chat_id=int(os.getenv("ADMIN_CHAT_ID", "0")),
            private_chat_id=int(os.getenv("PRIVATE_GROUP_ID", "0")),
            database_url=os.getenv(
                "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/greenlight"
            ),
            crm_webhook_url=os.getenv("CRM_WEBHOOK_URL", ""),
            crm_enabled=os.getenv("CRM_ENABLED", "false").lower() == "true",
            google_sheets_enabled=os.getenv("GOOGLE_SHEETS_ENABLED", "false").lower() == "true",
            google_credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", ""),
            spreadsheet_id=os.getenv("SPREADSHEET_ID", ""),
            sheet_name=os.getenv("SHEET_NAME", "Лиды"),
            sheet_name_client=os.getenv("SHEET_NAME_CLIENT", "Клиенты"),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
            work_start_hour=int(os.getenv("WORK_START_HOUR", "10")),
            work_end_hour=int(os.getenv("WORK_END_HOUR", "22")),
            sla_minutes=int(os.getenv("SLA_MINUTES", "30")),
            sla_warning_minutes=int(os.getenv("SLA_WARNING_MINUTES", "15")),
            sla_admin_minutes=int(os.getenv("SLA_ADMIN_MINUTES", "30")),
            sla_critical_minutes=int(os.getenv("SLA_CRITICAL_MINUTES", "120")),
            admin_ids=[int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()],
        )


config = Config.load()
