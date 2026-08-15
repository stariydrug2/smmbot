from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from keyboards.product import (
    analysis_menu_keyboard,
    channel_menu_keyboard,
    create_menu_keyboard,
    plan_menu_keyboard,
    results_keyboard,
)
from keyboards.reply import main_menu_keyboard
from services.usage_service import UsageService

router = Router()


async def _user(message: Message, queries: QueryService) -> dict | None:
    if not message.from_user:
        return None
    return await queries.get_user_by_telegram_id(message.from_user.id)


@router.callback_query(F.data.in_({'nav:main', 'go:menu'}))
async def nav_main(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer(
            '<b>Главное меню</b>\n\nВыберите, что сделать с вашим каналом.',
            reply_markup=main_menu_keyboard(callback.from_user.id in settings.admin_ids),
        )
    await callback.answer()


@router.message(F.text == '📣 Мой канал')
async def channel_section(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    await state.clear()
    user = await _user(message, queries)
    if not user:
        return
    channel = await product_repository.get_active_channel(int(user['id']))
    profile = await product_repository.get_channel_profile(int(channel['id'])) if channel else None
    if not channel:
        text = (
            '<b>Мой канал</b>\n\n'
            'Подключите Telegram-канал, чтобы KonturSMM учитывал его стиль, сохранял черновики '
            'и мог публиковать одобренные посты.'
        )
    else:
        username = f"@{channel['username']}" if channel.get('username') else 'без публичной ссылки'
        permissions = 'публикация доступна' if channel.get('bot_can_post') else 'нужно обновить права'
        setup = 'настроен' if profile and profile.get('is_complete') else 'нужно завершить настройку'
        text = (
            f"<b>{channel['title']}</b>\n"
            f"{username}\n\n"
            f"<b>Доступ:</b> {permissions}\n"
            f"<b>Профиль:</b> {setup}\n"
            f"<b>Часовой пояс:</b> {channel['timezone']}"
        )
    await message.answer(
        text,
        reply_markup=channel_menu_keyboard(bool(channel), bool(profile and profile.get('is_complete'))),
    )


@router.message(F.text == '✍️ Создать')
async def create_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '<b>Создать</b>\n\nВыберите результат. Я учту настройки подключённого канала.',
        reply_markup=create_menu_keyboard(),
    )


@router.message(F.text == '🗓 План')
async def plan_section(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '<b>План</b>\n\nСоберите план публикаций или проверьте уже запланированные посты.',
        reply_markup=plan_menu_keyboard(),
    )


@router.message(F.text == '🔎 Анализ')
async def analysis_section(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    await state.clear()
    user = await _user(message, queries)
    if not user:
        return
    channel = await product_repository.get_active_channel(int(user['id']))
    limits = await queries.get_user_limits(int(user['id']))
    await message.answer(
        '<b>Анализ</b>\n\nМожно разобрать один или несколько постов, весь накопленный контент канала '
        'или превратить найденную тему в оригинальные идеи.',
        reply_markup=analysis_menu_keyboard(
            channel_ready=bool(channel),
            topic_intercept=settings.feature_topic_intercept,
            expert_available=bool(
                int(limits.get('manual_post_reviews_left') or 0)
                or int(limits.get('channel_reviews_left') or 0)
            ),
            sources_enabled=settings.feature_competitor_sources,
        ),
    )


@router.message(F.text == '📈 Результаты')
async def results_section(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    usage_service: UsageService,
    settings: Settings,
) -> None:
    await state.clear()
    user = await _user(message, queries)
    if not user:
        return
    user_id = int(user['id'])
    results = await product_repository.get_results(user_id)
    access = await usage_service.status(user_id)
    trial = access['trial']
    limits = access['limits']
    trial_line = 'не активирован'
    if trial.get('status') == 'active':
        left = max(0, int(trial.get('generation_limit') or 0) - int(trial.get('generation_used') or 0))
        trial_line = f"активен, осталось действий: {left}"
    elif trial.get('status') in {'used', 'expired'}:
        trial_line = 'завершён'
    paid_left = sum(int(limits.get(field) or 0) for field in (
        'posts_left', 'cta_left', 'ideas_left', 'improvements_left', 'content_plans_left', 'voice_posts_left'
    ))
    await message.answer(
        '<b>Результаты работы</b>\n\n'
        f"Создано материалов: <b>{results['drafts']}</b>\n"
        f"Опубликовано через KonturSMM: <b>{results['published']}</b>\n"
        f"Запланировано: <b>{results['scheduled']}</b>\n"
        f"Проведено разборов: <b>{results['analyses']}</b>\n\n"
        f"Пробный доступ: <b>{trial_line}</b>\n"
        f"Платных AI-действий по основным лимитам: <b>{paid_left}</b>\n\n"
        'Здесь учитываются только фактические действия внутри KonturSMM. '
        'Просмотры и рост подписчиков бот не придумывает.',
        reply_markup=results_keyboard(settings.normalized_support_username),
    )
