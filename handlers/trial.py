from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from config import Settings
from database.queries import QueryService
from database.product_repository import ProductRepository
from keyboards.product import trial_continue_keyboard, trial_membership_keyboard
from services.trial_service import TrialService
from utils.helpers import escape_html, format_dt_human

router = Router()


async def _next_step(callback: CallbackQuery, user_id: int, trial_service: TrialService) -> None:
    if not callback.message:
        return
    ready = await trial_service.readiness(user_id)
    if not ready['membership_verified']:
        return
    if not ready['channel_connected']:
        await callback.message.answer(
            '<b>Шаг 2 из 3.</b> Подключите свой канал. Пробное время ещё не начнётся.',
            reply_markup=trial_continue_keyboard('channel'),
        )
    elif not ready['profile_complete']:
        await callback.message.answer(
            '<b>Шаг 3 из 3.</b> Настройте канал, чтобы первые генерации уже были полезными.',
            reply_markup=trial_continue_keyboard('profile'),
        )
    else:
        await callback.message.answer(
            'Всё готово. Нажмите кнопку в момент, когда готовы начать: отсчёт 24 часов пойдёт сразу.',
            reply_markup=trial_continue_keyboard('activate'),
        )


@router.callback_query(F.data == 'trial:start')
async def trial_start(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    trial_service: TrialService,
    settings: Settings,
    product_repository: ProductRepository,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    ready = await trial_service.readiness(int(user['id']))
    if ready['trial'].get('status') != 'none':
        await callback.answer('Пробный доступ уже активирован или завершён', show_alert=True)
        return
    if not ready['membership_verified']:
        verified = await trial_service.verify_membership(bot, int(user['id']), callback.from_user.id)
        if not verified:
            await callback.message.answer(
                '<b>Шаг 1 из 3.</b> Подпишитесь на канал KonturSMM и нажмите проверку. '
                'Бесплатный разбор от подписки не зависит.',
                reply_markup=trial_membership_keyboard(settings.channel_link),
            )
            await callback.answer()
            return
        await product_repository.log_activity(
            'trial_membership_verified',
            user_id=int(user['id']),
            telegram_id=int(user['telegram_id']),
            username=user.get('username'),
            full_name=user.get('full_name'),
        )
    await _next_step(callback, int(user['id']), trial_service)
    await callback.answer()


@router.callback_query(F.data == 'trial:verify')
async def trial_verify(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    trial_service: TrialService,
    product_repository: ProductRepository,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    verified = await trial_service.verify_membership(bot, int(user['id']), callback.from_user.id)
    if not verified:
        await callback.answer('Подписка пока не найдена', show_alert=True)
        return
    if callback.message:
        await callback.message.answer('<b>Подписка подтверждена.</b> Пробный период пока не запущен.')
    await product_repository.log_activity(
        'trial_membership_verified',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
    )
    await _next_step(callback, int(user['id']), trial_service)
    await callback.answer('Готово')


@router.callback_query(F.data == 'trial:activate')
async def trial_activate(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    trial_service: TrialService,
    product_repository: ProductRepository,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    if not await trial_service.verify_membership(bot, int(user['id']), callback.from_user.id):
        await callback.answer('Подписка на канал KonturSMM больше не найдена', show_alert=True)
        return
    try:
        trial = await trial_service.activate(int(user['id']))
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.message.answer(
        '<b>Пробный доступ активирован.</b>\n\n'
        f"Доступно AI-действий: <b>{trial['generation_limit']}</b>\n"
        f"Действует до: <b>{escape_html(format_dt_human(str(trial['ends_at'])))}</b>\n\n"
        'Создание, идеи, улучшения, планы и AI-разборы используют общий пробный счётчик. '
        'Публикация готового черновика его не списывает.'
    )
    await product_repository.log_activity(
        'trial_activated',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'ends_at': trial['ends_at'], 'generation_limit': trial['generation_limit']},
    )
    await callback.answer('Пробный доступ запущен')
