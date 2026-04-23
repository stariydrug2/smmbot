from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


DEFAULT_SUBSCRIPTION_PLANS = [
    {
        'code': '7d',
        'title': '7 дней',
        'duration_days': 7,
        'price_rub': 300,
        'is_active': True,
        'sort_order': 1,
    },
    {
        'code': '1m',
        'title': '1 месяц',
        'duration_days': 30,
        'price_rub': 800,
        'is_active': True,
        'sort_order': 2,
    },
    {
        'code': '6m',
        'title': '6 месяцев',
        'duration_days': 180,
        'price_rub': 3000,
        'is_active': True,
        'sort_order': 3,
    },
    {
        'code': '12m',
        'title': '1 год',
        'duration_days': 365,
        'price_rub': 5000,
        'is_active': True,
        'sort_order': 4,
    },
]


@dataclass(slots=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv('BOT_TOKEN', ''))
    openai_api_key: str = field(default_factory=lambda: os.getenv('OPENAI_API_KEY', ''))
    openai_text_model: str = field(default_factory=lambda: os.getenv('OPENAI_TEXT_MODEL', 'openai/gpt-5.4-nano'))
    openai_image_model: str = field(default_factory=lambda: os.getenv('OPENAI_IMAGE_MODEL', 'openai/gpt-image-1.5'))
    openai_transcribe_model: str = field(default_factory=lambda: os.getenv('OPENAI_TRANSCRIBE_MODEL', 'openai/gpt-4o-mini-transcribe'))
    channel_id: str = field(default_factory=lambda: os.getenv('CHANNEL_ID', ''))
    channel_link: str = field(default_factory=lambda: os.getenv('CHANNEL_LINK', ''))
    admin_ids_raw: str = field(default_factory=lambda: os.getenv('ADMIN_IDS', ''))
    database_path_raw: str = field(default_factory=lambda: os.getenv('DATABASE_PATH', 'data/bot.sqlite3'))
    payment_enabled: bool = field(default_factory=lambda: os.getenv('PAYMENT_ENABLED', 'false').lower() == 'true')
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))

    subscription_plans_json: str = field(default_factory=lambda: os.getenv('SUBSCRIPTION_PLANS_JSON', ''))
    trial_days: int = field(default_factory=lambda: int(os.getenv('TRIAL_DAYS', '3')))
    reminder_hours_before_end: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_HOURS', '24')))
    reminder_loop_interval_seconds: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_LOOP_SECONDS', '3600')))

    robokassa_merchant_login: str = field(default_factory=lambda: os.getenv('ROBOKASSA_MERCHANT_LOGIN', ''))
    robokassa_password_1: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_1', ''))
    robokassa_password_2: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_2', ''))
    robokassa_jwt_alg: str = field(default_factory=lambda: os.getenv('ROBOKASSA_JWT_ALG', 'MD5'))
    robokassa_create_invoice_url: str = field(default_factory=lambda: os.getenv('ROBOKASSA_CREATE_INVOICE_URL', 'https://services.robokassa.ru/InvoiceServiceWebApi/api/CreateInvoice'))
    robokassa_invoice_info_url: str = field(default_factory=lambda: os.getenv('ROBOKASSA_INVOICE_INFO_URL', 'https://services.robokassa.ru/InvoiceServiceWebApi/api/GetInvoiceInformationList'))
    robokassa_success_method: str = field(default_factory=lambda: os.getenv('ROBOKASSA_SUCCESS_METHOD', 'GET'))
    robokassa_fail_method: str = field(default_factory=lambda: os.getenv('ROBOKASSA_FAIL_METHOD', 'GET'))
    robokassa_culture: str = field(default_factory=lambda: os.getenv('ROBOKASSA_CULTURE', 'ru'))
    robokassa_tax: str = field(default_factory=lambda: os.getenv('ROBOKASSA_TAX', 'none'))
    robokassa_payment_method: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PAYMENT_METHOD', 'full_payment'))
    robokassa_payment_object: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PAYMENT_OBJECT', 'service'))

    app_base_url: str = field(default_factory=lambda: os.getenv('APP_BASE_URL', '').rstrip('/'))
    webapp_host: str = field(default_factory=lambda: os.getenv('WEBAPP_HOST', '0.0.0.0'))
    webapp_port: int = field(default_factory=lambda: int(os.getenv('WEBAPP_PORT', '8080')))

    @property
    def admin_ids(self) -> List[int]:
        return [int(v.strip()) for v in self.admin_ids_raw.split(',') if v.strip().isdigit()]

    @property
    def database_path(self) -> Path:
        path = Path(self.database_path_raw)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def subscription_plans(self) -> list[dict[str, Any]]:
        raw = self.subscription_plans_json.strip()
        if not raw:
            return DEFAULT_SUBSCRIPTION_PLANS
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return DEFAULT_SUBSCRIPTION_PLANS

    @property
    def robokassa_result_url(self) -> str:
        return f'{self.app_base_url}/payments/robokassa/result' if self.app_base_url else ''

    @property
    def robokassa_success_url(self) -> str:
        return f'{self.app_base_url}/payments/robokassa/success' if self.app_base_url else ''

    @property
    def robokassa_fail_url(self) -> str:
        return f'{self.app_base_url}/payments/robokassa/fail' if self.app_base_url else ''

    def validate(self) -> None:
        missing = []
        required = {
            'BOT_TOKEN': self.bot_token,
            'OPENAI_API_KEY': self.openai_api_key,
            'CHANNEL_ID': self.channel_id,
            'CHANNEL_LINK': self.channel_link,
        }
        for name, value in required.items():
            if not value:
                missing.append(name)

        if self.payment_enabled:
            payment_required = {
                'ROBOKASSA_MERCHANT_LOGIN': self.robokassa_merchant_login,
                'ROBOKASSA_PASSWORD_1': self.robokassa_password_1,
                'ROBOKASSA_PASSWORD_2': self.robokassa_password_2,
                'APP_BASE_URL': self.app_base_url,
            }
            for name, value in payment_required.items():
                if not value:
                    missing.append(name)

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


settings = Settings()
