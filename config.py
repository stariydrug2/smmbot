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
        'code': 'start',
        'title': 'Старт',
        'duration_days': 30,
        'price_rub': 390,
        'plan_type': 'one_time',
        'description': 'Пакет для первого знакомства с сервисом.',
        'limits': {
            'posts_left': 5,
            'cta_left': 5,
            'ideas_left': 5,
            'improvements_left': 1,
            'images_left': 2,
            'voice_posts_left': 0,
            'content_plans_left': 0,
            'channel_reviews_left': 0,
            'manual_post_reviews_left': 0,
        },
        'is_active': True,
        'sort_order': 1,
    },
    {
        'code': 'content_week',
        'title': 'Контент-неделя',
        'duration_days': 30,
        'price_rub': 790,
        'plan_type': 'one_time',
        'description': 'Пакет для подготовки контента на неделю.',
        'limits': {
            'posts_left': 10,
            'cta_left': 10,
            'ideas_left': 10,
            'improvements_left': 2,
            'images_left': 5,
            'voice_posts_left': 1,
            'content_plans_left': 1,
            'channel_reviews_left': 0,
            'manual_post_reviews_left': 0,
        },
        'is_active': True,
        'sort_order': 2,
    },
    {
        'code': 'restart',
        'title': 'Разморозка канала',
        'duration_days': 30,
        'price_rub': 1290,
        'plan_type': 'one_time',
        'description': 'Пакет для возвращения к регулярному контенту.',
        'limits': {
            'posts_left': 20,
            'cta_left': 20,
            'ideas_left': 10,
            'improvements_left': 3,
            'images_left': 8,
            'voice_posts_left': 3,
            'content_plans_left': 1,
            'channel_reviews_left': 0,
            'manual_post_reviews_left': 0,
        },
        'is_active': True,
        'sort_order': 3,
    },
    {
        'code': 'full_access',
        'title': 'Полный доступ',
        'duration_days': 30,
        'price_rub': 1490,
        'plan_type': 'subscription_30_days',
        'description': 'Для регулярного ведения Telegram-канала.',
        'limits': {
            'posts_left': 80,
            'cta_left': 80,
            'ideas_left': 80,
            'improvements_left': 80,
            'images_left': 10,
            'voice_posts_left': 30,
            'content_plans_left': 4,
            'channel_reviews_left': 0,
            'manual_post_reviews_left': 0,
        },
        'is_active': True,
        'sort_order': 4,
    },
    {
        'code': 'premium',
        'title': 'Premium',
        'duration_days': 30,
        'price_rub': 2990,
        'plan_type': 'subscription_30_days',
        'description': 'Для тех, кому нужен взгляд SMM-специалиста.',
        'limits': {
            'posts_left': 80,
            'cta_left': 80,
            'ideas_left': 80,
            'improvements_left': 80,
            'images_left': 40,
            'voice_posts_left': 30,
            'content_plans_left': 4,
            'channel_reviews_left': 1,
            'manual_post_reviews_left': 2,
        },
        'is_active': True,
        'sort_order': 5,
    },
]


@dataclass(slots=True)
class Settings:
    bot_token: str = field(
        default_factory=lambda: (
            os.getenv('BOT_TOKEN')
            or os.getenv('TELEGRAM_BOT_TOKEN')
            or os.getenv('TELEGRAM_TOKEN')
            or ''
        )
    )
    openai_api_key: str = field(
        default_factory=lambda: (
            os.getenv('OPENAI_API_KEY')
            or os.getenv('POLZA_API_KEY')
            or ''
        )
    )
    openai_text_model: str = field(default_factory=lambda: os.getenv('OPENAI_TEXT_MODEL', 'openai/gpt-5.4-nano'))
    openai_image_model: str = field(default_factory=lambda: os.getenv('OPENAI_IMAGE_MODEL', 'openai/gpt-image-1.5'))
    openai_transcribe_model: str = field(default_factory=lambda: os.getenv('OPENAI_TRANSCRIBE_MODEL', 'openai/gpt-4o-mini-transcribe'))
    channel_id: str = field(default_factory=lambda: os.getenv('CHANNEL_ID', ''))
    channel_link: str = field(default_factory=lambda: os.getenv('CHANNEL_LINK', ''))
    admin_ids_raw: str = field(default_factory=lambda: os.getenv('ADMIN_IDS', ''))
    database_path_raw: str = field(default_factory=lambda: os.getenv('DATABASE_PATH', 'data/bot.sqlite3'))
    payment_enabled: bool = field(default_factory=lambda: os.getenv('PAYMENT_ENABLED', 'false').lower() == 'true')
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    support_username: str = field(default_factory=lambda: os.getenv('SUPPORT_USERNAME', '@web3hooky'))

    subscription_plans_json: str = field(default_factory=lambda: os.getenv('SUBSCRIPTION_PLANS_JSON', ''))
    trial_days: int = field(default_factory=lambda: int(os.getenv('TRIAL_DAYS', '3')))
    reminder_hours_before_end: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_HOURS', '24')))
    reminder_loop_interval_seconds: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_LOOP_SECONDS', '3600')))

    robokassa_merchant_login: str = field(default_factory=lambda: os.getenv('ROBOKASSA_MERCHANT_LOGIN', ''))
    robokassa_password_1: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_1', ''))
    robokassa_password_2: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_2', ''))
    robokassa_is_test: bool = field(default_factory=lambda: os.getenv('ROBOKASSA_IS_TEST', 'false').lower() == 'true')
    robokassa_result_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_RESULT_URL', '').rstrip('/'))
    robokassa_success_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_SUCCESS_URL', '').rstrip('/'))
    robokassa_fail_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_FAIL_URL', '').rstrip('/'))
    robokassa_jwt_alg: str = field(default_factory=lambda: os.getenv('ROBOKASSA_JWT_ALG', 'MD5'))
    robokassa_create_invoice_url: str = field(
        default_factory=lambda: os.getenv(
            'ROBOKASSA_CREATE_INVOICE_URL',
            'https://services.robokassa.ru/InvoiceServiceWebApi/api/CreateInvoice',
        )
    )
    robokassa_invoice_info_url: str = field(
        default_factory=lambda: os.getenv(
            'ROBOKASSA_INVOICE_INFO_URL',
            'https://services.robokassa.ru/InvoiceServiceWebApi/api/GetInvoiceInformationList',
        )
    )
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
    def normalized_support_username(self) -> str:
        username = self.support_username.strip() or '@web3hooky'
        return username if username.startswith('@') else f'@{username}'

    @property
    def robokassa_result_url(self) -> str:
        if self.robokassa_result_url_raw:
            return self.robokassa_result_url_raw
        return f'{self.app_base_url}/payments/robokassa/result' if self.app_base_url else ''

    @property
    def robokassa_success_url(self) -> str:
        if self.robokassa_success_url_raw:
            return self.robokassa_success_url_raw
        return f'{self.app_base_url}/payments/robokassa/success' if self.app_base_url else ''

    @property
    def robokassa_fail_url(self) -> str:
        if self.robokassa_fail_url_raw:
            return self.robokassa_fail_url_raw
        return f'{self.app_base_url}/payments/robokassa/fail' if self.app_base_url else ''

    def validate(self) -> None:
        missing = []
        required = {
            'BOT_TOKEN': self.bot_token,
            'OPENAI_API_KEY': self.openai_api_key,
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
