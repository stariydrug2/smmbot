from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


@dataclass(slots=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv('BOT_TOKEN', ''))
    openai_api_key: str = field(default_factory=lambda: os.getenv('OPENAI_API_KEY', ''))
    openai_text_model: str = field(default_factory=lambda: os.getenv('OPENAI_TEXT_MODEL', 'gpt-4.1'))
    openai_image_model: str = field(default_factory=lambda: os.getenv('OPENAI_IMAGE_MODEL', 'gpt-image-1'))
    openai_transcribe_model: str = field(default_factory=lambda: os.getenv('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe'))
    channel_id: str = field(default_factory=lambda: os.getenv('CHANNEL_ID', ''))
    channel_link: str = field(default_factory=lambda: os.getenv('CHANNEL_LINK', ''))
    admin_ids_raw: str = field(default_factory=lambda: os.getenv('ADMIN_IDS', ''))
    database_path_raw: str = field(default_factory=lambda: os.getenv('DATABASE_PATH', 'data/bot.sqlite3'))
    payment_enabled: bool = field(default_factory=lambda: os.getenv('PAYMENT_ENABLED', 'false').lower() == 'true')
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))

    @property
    def admin_ids(self) -> List[int]:
        return [int(v.strip()) for v in self.admin_ids_raw.split(',') if v.strip().isdigit()]

    @property
    def database_path(self) -> Path:
        path = Path(self.database_path_raw)
        return path if path.is_absolute() else BASE_DIR / path

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
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


settings = Settings()
