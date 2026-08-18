from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(Path.cwd() / '.env')


def _clean_env(value: str | None) -> str:
    if not value:
        return ''
    return value.strip().strip('"').strip("'")


def _first_env(*names: str) -> str:
    for name in names:
        value = _clean_env(os.getenv(name))
        if value:
            return value
    return ''


def _env_bool(name: str, default: bool = False) -> bool:
    value = _clean_env(os.getenv(name)).lower()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'on'}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(_clean_env(os.getenv(name)) or default))
    except ValueError:
        return max(minimum, default)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(_clean_env(os.getenv(name)) or default))
    except ValueError:
        return max(minimum, default)


def _looks_like_telegram_token(value: str) -> bool:
    prefix, separator, suffix = value.partition(':')
    return bool(separator and prefix.isdigit() and len(suffix) >= 20)


def _first_telegram_token(*names: str) -> str:
    for name in names:
        value = _clean_env(os.getenv(name))
        if not value:
            continue
        if _looks_like_telegram_token(value):
            return value
    return ''

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
            _first_telegram_token(
                'KONTUR_BOT_TOKEN',
                'TELEGRAM_BOT_TOKEN',
                'TELEGRAM_TOKEN',
                'TG_BOT_TOKEN',
                'BOT_API_TOKEN',
                'TOKEN',
                'API_TOKEN',
                'BOT_TOKEN',
            )
        )
    )
    openai_api_key: str = field(
        default_factory=lambda: (
            _first_env('OPENAI_API_KEY', 'POLZA_API_KEY')
        )
    )
    gemini_api_key: str = field(
        default_factory=lambda: _first_env('KONTUR_GEMINI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY')
    )
    gemini_text_model: str = field(default_factory=lambda: _first_env('GEMINI_TEXT_MODEL') or 'gemini-3.1-flash-lite')
    openai_text_model: str = field(default_factory=lambda: os.getenv('OPENAI_TEXT_MODEL', 'openai/gpt-5.4-nano'))
    openai_image_model: str = field(default_factory=lambda: os.getenv('OPENAI_IMAGE_MODEL', 'openai/gpt-image-1.5'))
    openai_transcribe_model: str = field(default_factory=lambda: os.getenv('OPENAI_TRANSCRIBE_MODEL', 'openai/gpt-4o-mini-transcribe'))
    channel_id: str = field(default_factory=lambda: _first_env('KONTUR_CHANNEL_ID', 'CHANNEL_ID'))
    channel_link: str = field(default_factory=lambda: _first_env('KONTUR_CHANNEL_LINK', 'CHANNEL_LINK'))
    admin_ids_raw: str = field(default_factory=lambda: os.getenv('ADMIN_IDS', ''))
    database_path_raw: str = field(default_factory=lambda: os.getenv('DATABASE_PATH', 'data/bot.sqlite3'))
    payment_enabled: bool = field(default_factory=lambda: _env_bool('PAYMENT_ENABLED'))
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    support_username: str = field(default_factory=lambda: os.getenv('SUPPORT_USERNAME', '@web3hooky'))

    subscription_plans_json: str = field(default_factory=lambda: os.getenv('SUBSCRIPTION_PLANS_JSON', ''))
    # trial_days stays for compatibility with old deployments. New trial access is
    # controlled by hours and successful AI actions.
    trial_days: int = field(default_factory=lambda: _env_int('TRIAL_DAYS', 3, 1))
    trial_duration_hours: int = field(default_factory=lambda: _env_int('TRIAL_DURATION_HOURS', 24, 1))
    trial_generation_limit: int = field(default_factory=lambda: _env_int('TRIAL_GENERATION_LIMIT', 5, 1))
    reminder_hours_before_end: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_HOURS', '24')))
    reminder_loop_interval_seconds: int = field(default_factory=lambda: int(os.getenv('SUBSCRIPTION_REMINDER_LOOP_SECONDS', '3600')))

    robokassa_merchant_login: str = field(default_factory=lambda: os.getenv('ROBOKASSA_MERCHANT_LOGIN', ''))
    robokassa_password_1: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_1', ''))
    robokassa_password_2: str = field(default_factory=lambda: os.getenv('ROBOKASSA_PASSWORD_2', ''))
    robokassa_test_password_1: str = field(default_factory=lambda: os.getenv('ROBOKASSA_TEST_PASSWORD_1', ''))
    robokassa_test_password_2: str = field(default_factory=lambda: os.getenv('ROBOKASSA_TEST_PASSWORD_2', ''))
    robokassa_is_test: bool = field(default_factory=lambda: _env_bool('ROBOKASSA_IS_TEST'))
    robokassa_result_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_RESULT_URL', '').rstrip('/'))
    robokassa_success_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_SUCCESS_URL', '').rstrip('/'))
    robokassa_fail_url_raw: str = field(default_factory=lambda: os.getenv('ROBOKASSA_FAIL_URL', '').rstrip('/'))
    robokassa_jwt_alg: str = field(default_factory=lambda: os.getenv('ROBOKASSA_JWT_ALG', 'MD5'))
    robokassa_result_hash_alg: str = field(default_factory=lambda: os.getenv('ROBOKASSA_RESULT_HASH_ALG', 'MD5'))
    robokassa_create_invoice_url: str = field(
        default_factory=lambda: os.getenv(
            'ROBOKASSA_CREATE_INVOICE_URL',
            'https://services.robokassa.ru/InvoiceServiceWebApi/api/CreateInvoice',
        )
    )
    robokassa_invoice_info_url: str = field(
        default_factory=lambda: os.getenv(
            'ROBOKASSA_INVOICE_INFO_URL',
            'https://services.robokassa.ru/InvoiceServiceWebApi/api/GetInvoiceInformation',
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

    default_channel_timezone: str = field(default_factory=lambda: os.getenv('DEFAULT_CHANNEL_TIMEZONE', 'Europe/Moscow'))
    scheduler_interval_seconds: int = field(default_factory=lambda: _env_int('SCHEDULER_INTERVAL_SECONDS', 20, 5))
    scheduler_retry_seconds: int = field(default_factory=lambda: _env_int('SCHEDULER_RETRY_SECONDS', 120, 10))
    scheduler_max_retries: int = field(default_factory=lambda: _env_int('SCHEDULER_MAX_RETRIES', 3, 0))

    feature_channel_connect: bool = field(default_factory=lambda: _env_bool('FEATURE_CHANNEL_CONNECT', True))
    feature_publishing: bool = field(default_factory=lambda: _env_bool('FEATURE_PUBLISHING', True))
    feature_channel_analysis: bool = field(default_factory=lambda: _env_bool('FEATURE_CHANNEL_ANALYSIS', True))
    feature_topic_intercept: bool = field(default_factory=lambda: _env_bool('FEATURE_TOPIC_INTERCEPT', True))
    feature_competitor_sources: bool = field(default_factory=lambda: _env_bool('FEATURE_COMPETITOR_SOURCES', True))
    feature_competitor_monitoring: bool = field(default_factory=lambda: _env_bool('FEATURE_COMPETITOR_MONITORING', True))
    feature_proactive: bool = field(default_factory=lambda: _env_bool('FEATURE_PROACTIVE', True))
    feature_advanced_analytics: bool = field(default_factory=lambda: _env_bool('FEATURE_ADVANCED_ANALYTICS', False))

    competitor_check_interval_seconds: int = field(
        default_factory=lambda: _env_int('COMPETITOR_CHECK_INTERVAL_SECONDS', 900, 60)
    )
    competitor_http_timeout_seconds: int = field(
        default_factory=lambda: _env_int('COMPETITOR_HTTP_TIMEOUT_SECONDS', 20, 5)
    )
    competitor_max_sources: int = field(default_factory=lambda: _env_int('COMPETITOR_MAX_SOURCES', 10, 1))
    competitor_strong_multiplier: float = field(
        default_factory=lambda: _env_float('COMPETITOR_STRONG_MULTIPLIER', 1.5, 1.1)
    )
    competitor_strong_min_views: int = field(
        default_factory=lambda: _env_int('COMPETITOR_STRONG_MIN_VIEWS', 50, 1)
    )
    competitor_weekly_weekday: int = field(
        default_factory=lambda: min(6, _env_int('COMPETITOR_WEEKLY_WEEKDAY', 0, 0))
    )
    competitor_weekly_hour: int = field(
        default_factory=lambda: min(23, _env_int('COMPETITOR_WEEKLY_HOUR', 10, 0))
    )

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
            'KONTUR_CHANNEL_ID': self.channel_id,
            'KONTUR_CHANNEL_LINK': self.channel_link,
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
            visible_keys = sorted(
                key
                for key in os.environ
                if any(marker in key.upper() for marker in ('BOT', 'TOKEN', 'TELEGRAM', 'OPENAI', 'POLZA', 'GEMINI', 'GOOGLE'))
            )
            hint = (
                'Visible related env keys: '
                + (', '.join(visible_keys) if visible_keys else 'none')
                + '. Expected Telegram token in one of KONTUR_BOT_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_TOKEN, TG_BOT_TOKEN, BOT_API_TOKEN, TOKEN, API_TOKEN, BOT_TOKEN.'
            )
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}. {hint}")


settings = Settings()
