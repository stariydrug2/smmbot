from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from services.subscription_service import SubscriptionService
from utils.helpers import escape_html, normalize_username

router = Router()


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


@router.message(Command('admin'))
@router.message(F.text.in_({'🛠 Админка', 'Админка', ' Админка'}))
async def admin_panel(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return

    stats = await queries.get_admin_stats()
    logs = await queries.get_admin_logs(limit=5)
    latest = '\n'.join(
        [f"• {item.get('full_name') or item.get('first_name') or 'Пользователь'} — {item.get('created_at')}" for item in stats['latest_users']]
    ) or '—'
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
        '<b>Команды</b>\n'
        '• <code>/grant_access username</code> — безлимитный доступ\n'
        '• <code>/grant_access @username</code> — тоже работает\n'
        '• <code>/grant_access username 30</code> — доступ на 30 дней\n'
        '• <code>/revoke_access username</code> — отключить доступ\n'
        '• <code>/check_reminders</code> — вручную запустить проверку напоминаний\n\n'
        '<b>Важно:</b> выдать доступ можно только пользователю, который уже запускал бота хотя бы один раз.'
    )
    await message.answer(text)


@router.message(Command('grant_access'))
async def grant_access(message: Message, settings: Settings, subscription_service: SubscriptionService) -> None:
    if not _is_admin(message, settings):
        return

    parts = (message.text or '').split()
    if len(parts) < 2:
        await message.answer(
            '<b>Формат команды:</b>\n'
            '<code>/grant_access username</code> — безлимитно\n'
            '<code>/grant_access @username 30</code> — на 30 дней'
        )
        return

    username = normalize_username(parts[1])
    days = None
    if len(parts) >= 3:
        try:
            days = int(parts[2])
        except ValueError:
            await message.answer('Количество дней должно быть числом.')
            return

    status = await subscription_service.grant_access_by_username(username, days=days)
    if not status:
        await message.answer(
            f'Пользователь <code>@{escape_html(username)}</code> не найден.\n\n'
            'Он должен сначала открыть бота и нажать /start, чтобы попасть в базу.'
        )
        return

    mode = 'без ограничения' if days is None else f'на {days} дн.'
    await message.answer(
        '<b>Доступ выдан.</b>\n\n'
        f'<b>Логин:</b> @{escape_html(username)}\n'
        f'<b>Режим:</b> {escape_html(mode)}\n'
        f'<b>Статус:</b> {escape_html(str(status.get("status")))}\n'
        f'<b>Действует до:</b> {escape_html(str(status.get("ends_at_human") or "Без ограничения"))}'
    )


@router.message(Command('revoke_access'))
async def revoke_access(message: Message, settings: Settings, subscription_service: SubscriptionService) -> None:
    if not _is_admin(message, settings):
        return

    parts = (message.text or '').split()
    if len(parts) < 2:
        await message.answer('<b>Формат команды:</b>\n<code>/revoke_access username</code>')
        return

    username = normalize_username(parts[1])
    ok = await subscription_service.revoke_access_by_username(username)
    if not ok:
        await message.answer(
            f'Пользователь <code>@{escape_html(username)}</code> не найден.\n\n'
            'Он должен сначала открыть бота и нажать /start, чтобы попасть в базу.'
        )
        return

    await message.answer(
        '<b>Доступ отключён.</b>\n\n'
        f'<b>Логин:</b> @{escape_html(username)}'
    )


@router.message(Command('check_reminders'))
async def check_reminders(message: Message, settings: Settings, subscription_service: SubscriptionService) -> None:
    if not _is_admin(message, settings):
        return
    await subscription_service.send_expiring_reminders(message.bot)
    await message.answer('<b>Проверка напоминаний запущена.</b>')
