from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from config import Settings
from database.queries import QueryService

router = Router()


@router.message(F.text == '🛠 Админка')
async def admin_panel(message: Message, queries: QueryService, settings: Settings) -> None:
    if not message.from_user or message.from_user.id not in settings.admin_ids:
        return
    stats = await queries.get_admin_stats()
    logs = await queries.get_admin_logs(limit=5)
    latest = '\n'.join([f"• {item.get('full_name') or item.get('first_name') or 'Пользователь'} — {item.get('created_at')}" for item in stats['latest_users']]) or '—'
    log_lines = '\n'.join([f"• [{item['level']}] {item['action']}" for item in logs]) or '—'
    text = (
        '<b>Админка</b>\n\n'
        f"<b>Пользователей:</b> {stats['users']}\n"
        f"<b>Активных за 7 дней:</b> {stats['active_users']}\n"
        f"<b>Всего генераций:</b> {stats['generations']}\n"
        f"<b>Активных подписок:</b> {stats['active_subscriptions']}\n"
        f"<b>Истёкших подписок:</b> {stats['expired_subscriptions']}\n"
        f"<b>Успешных оплат:</b> {stats['paid_payments']}\n\n"
        f"<b>Последние регистрации:</b>\n{latest}\n\n"
        f"<b>Последние события:</b>\n{log_lines}\n\n"
        '<b>Состояние платежей:</b>\n'
        '• Robokassa invoice mode — включается через PAYMENT_ENABLED=true\n'
        '• ResultURL — должен смотреть в публичный webhook\n'
        '• Напоминания о подписке — отдельный фоновой цикл\n'
    )
    await message.answer(text)
