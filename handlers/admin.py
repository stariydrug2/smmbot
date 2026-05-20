from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from services.subscription_service import SubscriptionService
from utils.helpers import escape_html, format_dt_human, normalize_username, truncate

router = Router()
logger = logging.getLogger(__name__)

EVENT_TITLES = {
    'start_opened': 'Открыл /start',
    'subscription_gate_reached': 'Уперся в подписку на канал',
    'subscription_check_clicked': 'Проверил подписку на канал',
    'subscription_section_opened': 'Открыл подписку',
    'payment_section_opened': 'Открыл оплату',
    'payment_plan_clicked': 'Выбрал тариф',
    'payment_invoice_opened': 'Открыл счёт на оплату',
    'payment_check_clicked': 'Проверил оплату',
    'payment_history_opened': 'Открыл историю оплат',
    'content_create_opened': 'Открыл создание контента',
    'content_plan_opened': 'Открыл контент-план',
    'voice_mode_opened': 'Открыл голосовой режим',
    'visual_mode_opened': 'Открыл фото/визуал',
    'profile_opened': 'Открыл профиль',
    'history_opened': 'Открыл историю',
    'support_opened': 'Открыл поддержку',
    'voice_sent': 'Отправил голосовое',
    'photo_sent': 'Отправил фото',
    'document_sent': 'Отправил документ',
    'message_sent': 'Отправил сообщение',
}


def _is_admin(message: Message, settings: Settings) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


def _event_title(event_name: str) -> str:
    if event_name in EVENT_TITLES:
        return EVENT_TITLES[event_name]
    if event_name.startswith('content_action_'):
        return 'Кнопка результата: ' + event_name.replace('content_action_', '')
    if event_name.startswith('profile_action_'):
        return 'Профиль: ' + event_name.replace('profile_action_', '')
    if event_name.startswith('photo_action_'):
        return 'Фото/визуал: ' + event_name.replace('photo_action_', '')
    if event_name.startswith('voice_action_'):
        return 'Голосовое: ' + event_name.replace('voice_action_', '')
    if event_name.startswith('generation_mode_'):
        return 'Выбрал режим: ' + event_name.replace('generation_mode_', '').replace('_selected', '')
    return event_name


def _user_label(user: dict[str, Any]) -> str:
    username = user.get('username')
    if username:
        return f"@{escape_html(str(username))}"
    name = user.get('full_name') or user.get('first_name') or 'без username'
    return escape_html(str(name))


async def _ensure_activity_schema(queries: QueryService) -> None:
    # Same schema as ActivityMiddleware. Duplicated intentionally so /admin works
    # even before the first logged user action after deployment.
    await queries.db.execute(
        '''
        CREATE TABLE IF NOT EXISTS user_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            telegram_id INTEGER,
            username TEXT,
            full_name TEXT,
            event_type TEXT NOT NULL,
            event_name TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        '''
    )
    await queries.db.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_telegram_id ON user_activity_events(telegram_id)')
    await queries.db.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity_events(created_at)')
    await queries.db.execute('CREATE INDEX IF NOT EXISTS idx_user_activity_event_name ON user_activity_events(event_name)')


async def _find_user(queries: QueryService, identity: str) -> dict[str, Any] | None:
    value = identity.strip()
    username = normalize_username(value)
    if username:
        row = await queries.db.fetchone('SELECT * FROM users WHERE lower(username) = ?', (username,))
        if row:
            return dict(row)
    if value.isdigit():
        row = await queries.db.fetchone('SELECT * FROM users WHERE telegram_id = ?', (int(value),))
        if row:
            return dict(row)
    return None


async def _recent_activity(queries: QueryService, limit: int = 20, telegram_id: int | None = None) -> list[dict[str, Any]]:
    await _ensure_activity_schema(queries)
    if telegram_id:
        rows = await queries.db.fetchall(
            'SELECT * FROM user_activity_events WHERE telegram_id = ? ORDER BY id DESC LIMIT ?',
            (telegram_id, limit),
        )
    else:
        rows = await queries.db.fetchall(
            'SELECT * FROM user_activity_events ORDER BY id DESC LIMIT ?',
            (limit,),
        )
    return [dict(row) for row in rows]


def _format_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return '—'
    lines = []
    for item in events:
        username = item.get('username')
        who = f"@{escape_html(username)}" if username else escape_html(str(item.get('full_name') or item.get('telegram_id') or '—'))
        when = escape_html(format_dt_human(item.get('created_at')))
        title = escape_html(_event_title(str(item.get('event_name') or 'event')))
        lines.append(f'• {when} · {who} · {title}')
    return '\n'.join(lines)


async def _get_recent_users(queries: QueryService, limit: int = 30) -> list[dict[str, Any]]:
    await _ensure_activity_schema(queries)
    rows = await queries.db.fetchall(
        '''
        SELECT
            u.*,
            COUNT(e.id) AS events_count,
            MAX(e.created_at) AS last_activity_at,
            (
                SELECT e2.event_name
                FROM user_activity_events e2
                WHERE e2.telegram_id = u.telegram_id
                ORDER BY e2.id DESC
                LIMIT 1
            ) AS last_event_name,
            (
                SELECT COUNT(*)
                FROM generation_history gh
                WHERE gh.user_id = u.id
            ) AS generations_count
        FROM users u
        LEFT JOIN user_activity_events e ON e.telegram_id = u.telegram_id
        GROUP BY u.id
        ORDER BY COALESCE(last_activity_at, u.updated_at, u.created_at) DESC
        LIMIT ?
        ''',
        (limit,),
    )
    return [dict(row) for row in rows]


def _format_users_list(users: list[dict[str, Any]]) -> str:
    if not users:
        return 'Пользователей пока нет.'
    lines = ['<b>Последние пользователи</b>\n']
    for item in users:
        label = _user_label(item)
        last = format_dt_human(item.get('last_activity_at') or item.get('updated_at') or item.get('created_at'))
        event = _event_title(str(item.get('last_event_name') or '—'))
        generations = int(item.get('generations_count') or 0)
        events_count = int(item.get('events_count') or 0)
        lines.append(
            f'• {label} · id:<code>{item.get("telegram_id")}</code>\n'
            f'  Последнее: {escape_html(last)} · {escape_html(event)}\n'
            f'  Действий: {events_count} · Генераций: {generations}'
        )
    return '\n'.join(lines)


async def _build_funnel_text(queries: QueryService) -> str:
    await _ensure_activity_schema(queries)
    users = await queries.db.fetchone('SELECT COUNT(*) AS cnt FROM users')
    subscribed = await queries.db.fetchone('SELECT COUNT(*) AS cnt FROM users WHERE is_subscribed = 1')
    onboarded = await queries.db.fetchone('SELECT COUNT(*) AS cnt FROM users WHERE is_onboarding_completed = 1')
    generated = await queries.db.fetchone('SELECT COUNT(DISTINCT user_id) AS cnt FROM generation_history')
    active_subs = await queries.db.fetchone("SELECT COUNT(*) AS cnt FROM user_subscriptions WHERE status IN ('trial', 'active', 'manual', 'lifetime')")
    expired_subs = await queries.db.fetchone("SELECT COUNT(*) AS cnt FROM user_subscriptions WHERE status = 'expired'")
    paid = await queries.db.fetchone("SELECT COUNT(*) AS cnt FROM payments WHERE status = 'paid'")
    payment_clicks = await queries.db.fetchone("SELECT COUNT(DISTINCT telegram_id) AS cnt FROM user_activity_events WHERE event_name IN ('payment_section_opened', 'payment_plan_clicked', 'payment_invoice_opened')")
    stuck_gate = await queries.db.fetchone("SELECT COUNT(DISTINCT telegram_id) AS cnt FROM user_activity_events WHERE event_name = 'subscription_gate_reached'")

    return (
        '<b>Воронка</b>\n\n'
        f"<b>Пользователей в базе:</b> {int(users['cnt']) if users else 0}\n"
        f"<b>Подписались на канал:</b> {int(subscribed['cnt']) if subscribed else 0}\n"
        f"<b>Завершили онбординг:</b> {int(onboarded['cnt']) if onboarded else 0}\n"
        f"<b>Пробовали генерацию:</b> {int(generated['cnt']) if generated else 0}\n"
        f"<b>Открывали оплату:</b> {int(payment_clicks['cnt']) if payment_clicks else 0}\n"
        f"<b>Успешных оплат:</b> {int(paid['cnt']) if paid else 0}\n"
        f"<b>Активные/trial/manual:</b> {int(active_subs['cnt']) if active_subs else 0}\n"
        f"<b>Истёкшие:</b> {int(expired_subs['cnt']) if expired_subs else 0}\n"
        f"<b>Упирались в подписку на канал:</b> {int(stuck_gate['cnt']) if stuck_gate else 0}"
    )


async def _send_long(message: Message, text: str) -> None:
    # Telegram text limit is 4096 chars. Keep chunks smaller for safety.
    max_len = 3500
    if len(text) <= max_len:
        await message.answer(text)
        return
    chunk = ''
    for line in text.split('\n'):
        if len(chunk) + len(line) + 1 > max_len:
            await message.answer(chunk)
            chunk = ''
        chunk += line + '\n'
    if chunk.strip():
        await message.answer(chunk)


@router.message(Command('admin'))
@router.message(lambda message: bool(message.text and 'админка' in message.text.lower()))
async def admin_panel(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    await _ensure_activity_schema(queries)
    stats = await queries.get_admin_stats()
    logs = await queries.get_admin_logs(limit=5)
    recent_users = await _get_recent_users(queries, limit=7)
    recent_events = await _recent_activity(queries, limit=8)

    latest_users = '\n'.join(
        f"• {_user_label(item)} · {escape_html(_event_title(str(item.get('last_event_name') or '—')))}"
        for item in recent_users
    ) or '—'
    log_lines = '\n'.join([f"• [{escape_html(item['level'])}] {escape_html(item['action'])}" for item in logs]) or '—'

    text = (
        '<b>Админка</b>\n\n'
        f"<b>Пользователей:</b> {stats['users']}\n"
        f"<b>Активных за 7 дней:</b> {stats['active_users']}\n"
        f"<b>Всего генераций:</b> {stats['generations']}\n"
        f"<b>Активных подписок:</b> {stats['active_subscriptions']}\n"
        f"<b>Истёкших подписок:</b> {stats['expired_subscriptions']}\n"
        f"<b>Успешных оплат:</b> {stats['paid_payments']}\n\n"
        f"<b>Последние пользователи:</b>\n{latest_users}\n\n"
        f"<b>Последние действия:</b>\n{_format_events(recent_events)}\n\n"
        f"<b>Последние системные события:</b>\n{log_lines}\n\n"
        '<b>Команды</b>\n'
        '• <code>/users</code> — последние пользователи\n'
        '• <code>/user @username</code> — карточка пользователя\n'
        '• <code>/events @username</code> — действия пользователя\n'
        '• <code>/activity</code> — последние действия всех\n'
        '• <code>/funnel</code> — воронка\n'
        '• <code>/broadcast Текст</code> — рассылка всем\n'
        '• <code>/broadcast_to @user1 @user2 -- Текст</code> — выборочно\n'
        '• <code>/grant_access @username 30</code> — выдать доступ\n'
        '• <code>/revoke_access @username</code> — отключить доступ'
    )
    await _send_long(message, text)


@router.message(Command('users'))
async def users_list(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    users = await _get_recent_users(queries, limit=30)
    await _send_long(message, _format_users_list(users))


@router.message(Command('activity'))
async def recent_activity(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    events = await _recent_activity(queries, limit=30)
    await _send_long(message, '<b>Последние действия</b>\n\n' + _format_events(events))


@router.message(Command('events'))
async def user_events(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('<b>Формат:</b> <code>/events @username</code>')
        return
    user = await _find_user(queries, parts[1])
    if not user:
        await message.answer(f'Пользователь <code>{escape_html(parts[1])}</code> не найден.')
        return
    events = await _recent_activity(queries, limit=40, telegram_id=int(user['telegram_id']))
    await _send_long(message, f'<b>Действия {_user_label(user)}</b>\n\n' + _format_events(events))


@router.message(Command('user'))
async def user_card(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('<b>Формат:</b> <code>/user @username</code>')
        return
    user = await _find_user(queries, parts[1])
    if not user:
        await message.answer(f'Пользователь <code>{escape_html(parts[1])}</code> не найден.')
        return

    subscription = await queries.get_user_subscription(int(user['id']))
    generations = await queries.db.fetchone('SELECT COUNT(*) AS cnt FROM generation_history WHERE user_id = ?', (user['id'],))
    payments = await queries.db.fetchone('SELECT COUNT(*) AS cnt FROM payments WHERE user_id = ?', (user['id'],))
    paid = await queries.db.fetchone("SELECT COUNT(*) AS cnt FROM payments WHERE user_id = ? AND status = 'paid'", (user['id'],))
    events = await _recent_activity(queries, limit=12, telegram_id=int(user['telegram_id']))
    event_counter = Counter([str(item.get('event_name')) for item in events])
    top_events = '\n'.join(
        f'• {escape_html(_event_title(name))}: {count}' for name, count in event_counter.most_common(5)
    ) or '—'

    text = (
        f'<b>Пользователь {_user_label(user)}</b>\n\n'
        f"<b>Telegram ID:</b> <code>{user.get('telegram_id')}</code>\n"
        f"<b>Имя:</b> {escape_html(str(user.get('full_name') or user.get('first_name') or '—'))}\n"
        f"<b>Канал:</b> {'да' if user.get('is_subscribed') else 'нет'}\n"
        f"<b>Онбординг:</b> {'да' if user.get('is_onboarding_completed') else 'нет'}\n"
        f"<b>Админ:</b> {'да' if user.get('is_admin') else 'нет'}\n"
        f"<b>Регистрация:</b> {escape_html(format_dt_human(user.get('created_at')))}\n\n"
        f"<b>Подписка:</b> {escape_html(str(subscription.get('status') if subscription else '—'))}\n"
        f"<b>До:</b> {escape_html(format_dt_human(subscription.get('ends_at') if subscription else None))}\n\n"
        f"<b>Генераций:</b> {int(generations['cnt']) if generations else 0}\n"
        f"<b>Платежей:</b> {int(payments['cnt']) if payments else 0}\n"
        f"<b>Успешных оплат:</b> {int(paid['cnt']) if paid else 0}\n\n"
        f"<b>Топ последних действий:</b>\n{top_events}\n\n"
        f"<b>Последние действия:</b>\n{_format_events(events)}"
    )
    await _send_long(message, text)


@router.message(Command('funnel'))
async def funnel(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    await message.answer(await _build_funnel_text(queries))


@router.message(Command('grant_access'))
async def grant_access(message: Message, settings: Settings, subscription_service: SubscriptionService) -> None:
    if not _is_admin(message, settings):
        return
    parts = (message.text or '').split()
    if len(parts) < 2:
        await message.answer(
            '<b>Формат команды:</b>\n'
            '<code>/grant_access username</code> — безлимитно\n'
            '<code>/grant_access username 30</code> — на 30 дней'
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
        f'<b>Логин:</b> @{escape_html(normalize_username(username) or username.lstrip("@"))}\n'
        f'<b>Режим:</b> {mode}\n'
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
        f'<b>Логин:</b> @{escape_html(normalize_username(username) or username.lstrip("@"))}'
    )


@router.message(Command('check_reminders'))
async def check_reminders(message: Message, settings: Settings, subscription_service: SubscriptionService) -> None:
    if not _is_admin(message, settings):
        return
    try:
        await subscription_service.send_expiring_reminders(message.bot)
        sent = None
    except AttributeError:
        await message.answer('В текущем сервисе нет ручного метода проверки напоминаний.')
        return
    await message.answer('<b>Проверка напоминаний завершена.</b>')


@router.message(Command('broadcast'))
async def broadcast(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    text = (message.text or '').partition(' ')[2].strip()
    if not text:
        await message.answer('<b>Формат:</b> <code>/broadcast Текст рассылки</code>')
        return

    rows = await queries.db.fetchall('SELECT telegram_id FROM users ORDER BY id ASC')
    ok = 0
    failed = 0
    for row in rows:
        try:
            await message.bot.send_message(chat_id=int(row['telegram_id']), text=text)
            ok += 1
        except Exception:
            failed += 1
            logger.exception('Broadcast failed for %s', row['telegram_id'])
    await message.answer(f'<b>Рассылка завершена.</b>\nУспешно: {ok}\nОшибок: {failed}')


@router.message(Command('broadcast_to'))
async def broadcast_to(message: Message, queries: QueryService, settings: Settings) -> None:
    if not _is_admin(message, settings):
        return
    raw = (message.text or '').partition(' ')[2].strip()
    if ' -- ' not in raw:
        await message.answer('<b>Формат:</b> <code>/broadcast_to @user1 @user2 -- Текст</code>')
        return
    users_part, _, text = raw.partition(' -- ')
    targets = [item for item in users_part.split() if item.strip()]
    if not targets or not text.strip():
        await message.answer('<b>Формат:</b> <code>/broadcast_to @user1 @user2 -- Текст</code>')
        return

    ok = 0
    failed = 0
    missing: list[str] = []
    for target in targets:
        user = await _find_user(queries, target)
        if not user:
            missing.append(target)
            continue
        try:
            await message.bot.send_message(chat_id=int(user['telegram_id']), text=text.strip())
            ok += 1
        except Exception:
            failed += 1
            logger.exception('Selective broadcast failed for %s', target)

    result = f'<b>Выборочная рассылка завершена.</b>\nУспешно: {ok}\nОшибок: {failed}'
    if missing:
        result += '\nНе найдены: ' + ', '.join(escape_html(item) for item in missing)
    await message.answer(result)
