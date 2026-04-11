# Telegram AI Content Operator

Telegram-first бот для создания контента бизнеса с помощью OpenAI: посты, контент-планы, CTA, story-анонсы, идеи визуалов, генерация материалов из голосовых и фото.

## Что умеет MVP

- проверка подписки на канал перед доступом к функциям
- пошаговый онбординг и сохранение профиля бренда
- главное меню с ключевыми сценариями
- генерация контента под Telegram
- контент-план на 7 дней
- рерайт, CTA, story-анонс, серия постов
- распознавание голосовых через OpenAI
- базовая работа с фото и генерация изображения
- история генераций
- личный кабинет и редактирование профиля
- brand memory summary
- минимальная админка
- архитектурные заготовки под trial, подписку и рефералку

## Стек

- Python 3.11+
- aiogram 3.x
- SQLite + aiosqlite
- OpenAI Python SDK
- python-dotenv

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Linux / macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Настройка `.env`

1. Скопируйте пример:

```bash
cp .env.example .env
```

2. Заполните переменные:

```env
BOT_TOKEN=
OPENAI_API_KEY=
OPENAI_TEXT_MODEL=gpt-4.1
OPENAI_IMAGE_MODEL=gpt-image-1
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
CHANNEL_ID=
CHANNEL_LINK=
ADMIN_IDS=123456789,987654321
DATABASE_PATH=data/bot.sqlite3
PAYMENT_ENABLED=false
LOG_LEVEL=INFO
```

## Как запустить

```bash
python bot.py
```

## Важно по каналу

Для корректной проверки подписки бот должен быть администратором канала. Иначе `get_chat_member` может работать нестабильно или возвращать ошибку доступа.

Нужно указать:

- `CHANNEL_ID` — id канала, например `-100xxxxxxxxxx`
- `CHANNEL_LINK` — публичную ссылку на канал

## Структура данных

SQLite создаётся автоматически при первом запуске.

Основные таблицы:

- `users`
- `brand_profiles`
- `user_examples`
- `brand_memory_summaries`
- `generation_history`
- `subscriptions_stub`
- `referrals_stub`
- `admin_logs`

## Что подготовлено на будущее

- логика 3-дневного trial
- архитектура подписки
- архитектура реферальной системы
- stub под broadcast и события админки
- возможность замены FSM storage без переписывания бизнес-логики

## Примечания

- бот работает только на русском языке
- `parse_mode=HTML` включён глобально
- ссылки как пользовательский вход для генерации сейчас не поддерживаются
- web UI и тяжёлые панели намеренно не используются — только Telegram-first сценарий
