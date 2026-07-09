# KonturSMM Telegram Bot

Telegram-бот для анализа, усиления и создания контента для Telegram-каналов.

Главный путь пользователя:

1. Пользователь заходит в бота.
2. Отправляет Telegram-пост.
3. Получает один бесплатный экспресс-анализ.
4. Покупает тариф.
5. Работает по лимитам: посты, CTA, идеи, улучшения, изображения, голосовые и Premium-заявки.

## Что умеет

- бесплатный анализ поста один раз на пользователя;
- генерация постов, CTA, идей, контент-планов;
- улучшение присланных постов;
- генерация изображений через существующий image-сервис;
- голос → пост через существующую транскрибацию;
- лимиты по каждому типу платной функции;
- Robokassa ResultURL с проверкой подписи и начислением лимитов;
- Premium-заявки на ручной разбор канала или поста;
- Telegram-админка для пользователей, оплат, тарифов, лимитов и Premium-заявок.

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

Ключевые переменные:

- `BOT_TOKEN`
- `OPENAI_API_KEY`
- `ADMIN_IDS`
- `PAYMENT_ENABLED`
- `APP_BASE_URL`
- `ROBOKASSA_MERCHANT_LOGIN`
- `ROBOKASSA_PASSWORD_1`
- `ROBOKASSA_PASSWORD_2`
- `ROBOKASSA_IS_TEST`
- `ROBOKASSA_RESULT_URL`
- `ROBOKASSA_SUCCESS_URL`
- `ROBOKASSA_FAIL_URL`

## Тарифы

По умолчанию зашиты:

- `start` - Старт, 390 ₽;
- `content_week` - Контент-неделя, 790 ₽;
- `restart` - Разморозка канала, 1290 ₽;
- `full_access` - Полный доступ на 30 дней, 1490 ₽;
- `premium` - Premium на 30 дней, 2990 ₽.

Лимиты тарифов задаются в `DEFAULT_SUBSCRIPTION_PLANS` или через `SUBSCRIPTION_PLANS_JSON`.

## Robokassa

Основное подтверждение оплаты идет через серверный `ResultURL`. SuccessURL и FailURL используются только как пользовательские страницы.

В кабинете Robokassa проверьте:

- MerchantLogin;
- Пароль №1 и Пароль №2;
- ResultURL;
- SuccessURL;
- FailURL;
- тестовый режим;
- фискализацию и названия услуг в чеках.

## Запуск

```bash
python bot.py
```

При `PAYMENT_ENABLED=true` бот поднимает:

- Telegram polling;
- HTTP-сервер для Robokassa;
- фоновые напоминания по активным тарифам.

## Админ-команды

- `/admin`
- `/users`
- `/orders`
- `/premium_requests`
- `/premium_request 1`
- `/reply_premium 1 текст ответа`
- `/grant_tariff @username start`
- `/set_limits @username posts_left 10`
- `/reset_free_analysis @username`
- `/broadcast Текст`
