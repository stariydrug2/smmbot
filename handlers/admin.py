from __future__ import annotations

import asyncio
from typing import Iterable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from services.subscription_service import SubscriptionService
from utils.helpers import escape_html, format_dt_human, render_model_text

router = Router()


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


def _normalize_username(username: str) -> str:
    return username.strip().lstrip('@').lower()


def _format_user_line(user: dict) -> str:
    username = user.get('username')
    tg_id = user.get('telegram_id')
    created_at = format_dt_human(user.get('created_at'))
    name = user.get('full_name') or user.get('first_name') or 'без имени'
    if username:
        return f'• @{escape_html(username)} · id:{tg_id} · {escape_html(created_at)}'
    return f'• {escape_html(name)} · id:{tg_id} · {escape_html(created_at)}'


async def _fetch_recent_users(queries: QueryService, limit: int = 10) -> list[dict]:
    rows = await queries.db.fetchall(
        '''
        SELECT telegram_id, username, first_name, full_name, created_at
        FROM users
        ORDER BY id DESC
        LIMIT ?
        ''',
        (limit,),
    )
    return [dict(row) for row in rows]


async def _fetch_all_users(queries: QueryService) -> list[dict]:
    rows = await queries.db.fetchall(
        '''
        SELECT telegram_id, username, first_name, full_name, created_at
        FROM users
        ORDER BY id ASC
        '''
    )
    return [dict(row) for row in rows]


async def _fetch_users_by_usernames(queries: QueryService, usernames: Iterable[str]) -> list[dict]:
    normalized = [_normalize_username(username) for username in usernames if _normalize_username(username)]
    if not normalized:
        return []
    placeholders = ','.join(['?'] * len(normalized))
    rows = await queries.db.fetchall(
        f'''
        SELECT telegram_id, username, first_name, full_name, created_at
        FROM users
        WHERE LOWER(username) IN ({placeholders})
        ORDER BY id ASC
        ''',
        normalized,
    )
    return [dict(row) for row in rows]


async def _send_broadcast(message: Message, users: list[dict], text: str) -> tuple[int, int]:
    sent = 0
    failed = 0
    prepared_text = render_model_text(text)
    for user in users:
        try:
            await message.bot.send_message(chat_id=int(user['telegram_id']), text=prepared_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    return sent, failed


@router.message(Command('admin'))
@router.message(F.text.in_({'🛠 Админка', 'Админка'}))
async def admin_panel(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return

    stats = await queries.get_admin_stats()
    logs = await queries.get_admin_logs(limit=5)
    recent_users = await _fetch_recent_users(queries, limit=10)

    latest = '\n'.join(_format_user_line(item) for item in recent_users) or '—'
    log_lines = '\n'.join([f"• [{escape_html(item['level'])}] {escape_html(item['action'])}" for item in logs]) or '—'

    text = (
        '<b>Админка</b>\n\n'
        f"<b>Пользователей:</b> {stats['users']}\n"
        f"<b>Активных за 7 дней:</b> {stats['active_users']}\n"
        f"<b>Всего генераций:</b> {stats['generations']}\n"
        f"<b>Активных подписок:</b> {stats.get('active_subscriptions', 0)}\n"
        f"<b>Истёкших подписок:</b> {stats.get('expired_subscriptions', 0)}\n"
        f"<b>Успешных оплат:</b> {stats.get('paid_payments', 0)}\n\n"
        f"<b>Последние пользователи:</b>\n{latest}\n\n"
        f"<b>Последние события:</b>\n{log_lines}\n\n"
        '<b>Команды доступа</b>\n'
        '• <code>/grant_access username</code> — безлимитный доступ\n'
        '• <code>/grant_access @username 30</code> — доступ на 30 дней\n'
        '• <code>/revoke_access @username</code> — отключить доступ\n\n'
        '<b>Рассылки</b>\n'
        '• <code>/broadcast текст</code> — всем пользователям\n'
        '• <code>/broadcast_to @user1 @user2 -- текст</code> — выборочно\n'
        '• <code>/users</code> — последние 30 пользователей'
    )
    await message.answer(text)


@router.message(Command('users'))
async def list_users(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    users = await _fetch_recent_users(queries, limit=30)
    text = '<b>Последние пользователи</b>\n\n' + ('\n'.join(_format_user_line(user) for user in users) or '—')
    await message.answer(text)


@router.message(Command('broadcast'))
async def broadcast_all(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return

    command, _, payload = (message.text or '').partition(' ')
    if not payload.strip():
        await message.answer(
            '<b>Формат рассылки:</b>\n'
            '<code>/broadcast Текст сообщения</code>\n\n'
            'Сообщение уйдёт всем пользователям, которые запускали бота.'
        )
        return

    users = await _fetch_all_users(queries)
    await message.answer(f'<b>Рассылка запущена.</b>\nПолучателей: {len(users)}')
    sent, failed = await _send_broadcast(message, users, payload.strip())
    await message.answer(f'<b>Рассылка завершена.</b>\nОтправлено: {sent}\nОшибок: {failed}')


@router.message(Command('broadcast_to'))
async def broadcast_selected(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return

    _, _, payload = (message.text or '').partition(' ')
    if '--' not in payload:
        await message.answer(
            '<b>Формат выборочной рассылки:</b>\n'
            '<code>/broadcast_to @user1 @user2 -- Текст сообщения</code>'
        )
        return

    targets_raw, text = payload.split('--', maxsplit=1)
    targets = [item.strip().strip(',') for item in targets_raw.replace(',', ' ').split() if item.strip()]
    if not targets or not text.strip():
        await message.answer(
            '<b>Формат выборочной рассылки:</b>\n'
            '<code>/broadcast_to @user1 @user2 -- Текст сообщения</code>'
        )
        return

    users = await _fetch_users_by_usernames(queries, targets)
    if not users:
        await message.answer('Пользователи с такими username не найдены. Они должны хотя бы раз запускать бота.')
        return

    await message.answer(f'<b>Выборочная рассылка запущена.</b>\nПолучателей: {len(users)}')
    sent, failed = await _send_broadcast(message, users, text.strip())
    await message.answer(f'<b>Рассылка завершена.</b>\nОтправлено: {sent}\nОшибок: {failed}')


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

    username = parts[1]
    days = None
    if len(parts) >= 3:
        try:
            days = int(parts[2])
        except ValueError:
            await message.answer('Количество дней должно быть числом.')
            return

    status = await subscription_service.grant_access_by_username(username, days=days)
    if not status:
        await message.answer(f'Пользователь <code>{escape_html(username)}</code> не найден.')
        return

    mode = 'без ограничения' if days is None else f'на {days} дн.'
    await message.answer(
        '<b>Доступ выдан.</b>\n\n'
        f'<b>Логин:</b> @{escape_html(username.lstrip("@"))}\n'
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

    username = parts[1]
    ok = await subscription_service.revoke_access_by_username(username)
    if not ok:
        await message.answer(f'Пользователь <code>{escape_html(username)}</code> не найден.')
        return

    await message.answer(
        '<b>Доступ отключён.</b>\n\n'
        f'<b>Логин:</b> @{escape_html(username.lstrip("@"))}'
    )
