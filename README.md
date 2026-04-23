# Telegram AI Content Operator

Telegram-first бот для создания контента бизнеса с помощью AI: посты, контент-планы, CTA, story-анонсы, идеи визуалов, генерация материалов из голосовых и фото.

## Что умеет

- проверка подписки на канал
- онбординг и профиль бренда
- генерация контента и история генераций
- голосовые, фото и визуальные сценарии
- платная подписка через Robokassa Invoice API
- продление подписки при повторной оплате
- напоминание за 24 часа до конца подписки
- профиль с текущим статусом и историей оплат
- webhook ResultURL для автоматической активации оплаты

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Настройка `.env`

Скопируйте пример:

```bash
cp .env.example .env
```

Заполните базовые поля и платежные настройки.

### Ключевые переменные для подписок

- `PAYMENT_ENABLED=true`
- `ROBOKASSA_MERCHANT_LOGIN`
- `ROBOKASSA_PASSWORD_1`
- `ROBOKASSA_PASSWORD_2`
- `APP_BASE_URL` — публичный базовый URL сервера, например `https://example.com`
- `WEBAPP_PORT` — локальный порт встроенного webhook-сервера

### Тарифы

По умолчанию уже зашиты:

- 7 дней — 300 ₽
- 1 месяц — 800 ₽
- 6 месяцев — 3000 ₽
- 1 год — 5000 ₽

Если нужно добавить или отключить тарифы, меняйте `SUBSCRIPTION_PLANS_JSON`.

## Важно по Robokassa

В личном кабинете Robokassa настройте:

- `ResultURL` → `https://ВАШ_ДОМЕН/payments/robokassa/result`
- `SuccessURL` можно оставить как служебный или использовать страницы сервера
- `FailURL` аналогично

Основное подтверждение оплаты идёт через `ResultURL`. Бот продлевает подписку автоматически только после успешного серверного callback.

## Запуск

```bash
python bot.py
```

При `PAYMENT_ENABLED=true` бот поднимает:

- Telegram polling
- HTTP webhook-сервер для Robokassa
- фоновый цикл напоминаний о скором окончании подписки

## Что уже заложено архитектурно

- `subscription_plans`
- `payments`
- `user_subscriptions`
- `payment_events`
- `subscription_notifications`

## Что можно улучшить позже

- отдельная mini-admin панель по платежам
- ручные возвраты и отмены
- автоотключение старых неоплаченных счетов
- отдельный worker/cron вместо фонового цикла
