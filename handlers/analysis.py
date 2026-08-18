from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from handlers.content import _deny_access, _send_model_text
from keyboards.product import (
    analysis_collect_keyboard,
    competitor_digest_keyboard,
    competitor_sources_keyboard,
    draft_actions_keyboard,
    expert_review_keyboard,
    trial_offer_keyboard,
)
from services.competitor_service import CompetitorFeedError, CompetitorMonitoringService
from services.content_service import ContentService
from services.usage_service import AccessRequiredError, UsageService
from states.product_states import AnalysisStates
from utils.helpers import escape_html

router = Router()


async def _show_competitor_sources(
    message: Message,
    user_id: int,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    sources = await product_repository.list_competitor_sources(user_id)
    monitor_settings = await product_repository.get_competitor_settings(user_id)
    lines = ['<b>📡 Радар ниши</b>', '']
    if sources:
        for item in sources:
            title = item.get('title') or f"@{item.get('username') or 'channel'}"
            username = f"@{item['username']}" if item.get('username') else str(item.get('source_url') or '')
            status = 'есть ошибка' if item.get('last_error') else ('проверяется' if item.get('initialized_at') else 'ожидает первой проверки')
            lines.append(f"• <b>{escape_html(str(title))}</b> · {escape_html(username)} · {status}")
            if item.get('last_error'):
                lines.append(f"  {escape_html(str(item['last_error'])[:180])}")
    else:
        lines.append('Добавьте публичные каналы, за темами и сильными постами которых хотите следить.')

    if settings.feature_competitor_monitoring:
        lines.append(
            '\nБот проверяет открытые публикации, сравнивает просмотры с обычным уровнем каждого канала '
            'и собирает недельный Пульс ниши.'
        )
    else:
        lines.append('\nФоновая проверка выключена на сервере. Кнопка «Проверить сейчас» продолжает работать.')
    if bool(monitor_settings.get('weekly_plan_enabled')):
        lines.append('AI-план создаётся раз в неделю и списывает один лимит контент-плана только при успехе.')
    await message.answer('\n'.join(lines), reply_markup=competitor_sources_keyboard(sources, monitor_settings))


@router.callback_query(F.data == 'analysis:sources')
async def competitor_sources(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer('Пользователь не найден', show_alert=True)
        return
    await _show_competitor_sources(callback.message, int(user['id']), product_repository, settings)
    await callback.answer()


@router.callback_query(F.data == 'analysis:source_add')
async def competitor_source_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await state.clear()
        await state.set_state(AnalysisStates.competitor_source)
        await callback.message.answer('Пришлите ссылку вида <code>https://t.me/channel</code> или <code>@channel</code>.')
    await callback.answer()


@router.message(AnalysisStates.competitor_source, F.text)
async def competitor_source_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    competitor_service: CompetitorMonitoringService,
    settings: Settings,
) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        return
    await message.answer('Проверяю публичную страницу и сохраняю последние публикации…')
    try:
        source, posts_count = await competitor_service.register_source(int(user['id']), message.text.strip())
    except CompetitorFeedError as exc:
        await message.answer(f'<b>Источник не добавлен.</b>\n\n{escape_html(str(exc))}')
        return
    except Exception:
        await message.answer('Не удалось проверить источник. Попробуйте ещё раз немного позже.')
        return
    finally:
        await state.clear()
    await product_repository.log_activity(
        'competitor_source_added',
        user_id=int(user['id']),
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        payload={'source_id': int(source['id']), 'seeded_posts': posts_count},
    )
    await message.answer(
        f"<b>{escape_html(str(source.get('title') or source.get('username')))}</b> добавлен. "
        f"Сохранено публикаций для начального сравнения: <b>{posts_count}</b>. Старые уведомления отправлены не будут."
    )
    await _show_competitor_sources(message, int(user['id']), product_repository, settings)


@router.callback_query(F.data.startswith('analysis:source_remove:'))
async def competitor_source_remove(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    source_id = int(callback.data.rsplit(':', 1)[1])
    removed = await product_repository.remove_competitor_source(source_id, int(user['id'])) if user else False
    await callback.answer('Источник удалён' if removed else 'Источник не найден', show_alert=not removed)
    if removed and callback.message and user:
        await _show_competitor_sources(callback.message, int(user['id']), product_repository, settings)


@router.callback_query(F.data == 'analysis:sources_sync')
async def competitor_sources_sync(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    competitor_service: CompetitorMonitoringService,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    await callback.answer('Проверяю источники')
    await callback.message.answer('Сверяю новые публикации и обновляю показатели…')
    try:
        summary = await competitor_service.sync_user(bot, int(user['id']))
    except Exception:
        await callback.message.answer('Проверка прервалась из-за временной ошибки. Фоновая работа бота не затронута.')
        return
    await callback.message.answer(
        '<b>Проверка завершена.</b>\n\n'
        f"Источников проверено: <b>{summary.sources_checked}</b>\n"
        f"Новых постов: <b>{summary.new_posts}</b>\n"
        f"Новых сильных сигналов: <b>{summary.strong_posts}</b>\n"
        f"Ошибок: <b>{summary.errors}</b>"
    )


@router.callback_query(F.data == 'analysis:notify_cycle')
async def competitor_notify_cycle(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    current = await product_repository.get_competitor_settings(int(user['id']))
    next_mode = {'strong': 'all', 'all': 'off', 'off': 'strong'}.get(str(current.get('notify_mode')), 'strong')
    await product_repository.update_competitor_settings(int(user['id']), notify_mode=next_mode)
    labels = {'strong': 'только сильные посты', 'all': 'все новые посты', 'off': 'уведомления выключены'}
    await callback.answer(labels[next_mode])
    await _show_competitor_sources(callback.message, int(user['id']), product_repository, settings)


@router.callback_query(F.data == 'analysis:pulse_toggle')
async def competitor_pulse_toggle(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    current = await product_repository.get_competitor_settings(int(user['id']))
    enabled = not bool(current.get('pulse_enabled'))
    await product_repository.update_competitor_settings(int(user['id']), pulse_enabled=int(enabled))
    await callback.answer('Пульс недели включён' if enabled else 'Пульс недели выключен')
    await _show_competitor_sources(callback.message, int(user['id']), product_repository, settings)


@router.callback_query(F.data == 'analysis:plan_toggle')
async def competitor_plan_toggle(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    if not settings.feature_proactive:
        await callback.answer('Проактивные планы выключены на сервере', show_alert=True)
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    current = await product_repository.get_competitor_settings(int(user['id']))
    enabled = not bool(current.get('weekly_plan_enabled'))
    await product_repository.update_competitor_settings(int(user['id']), weekly_plan_enabled=int(enabled))
    await callback.answer('AI-план недели включён' if enabled else 'AI-план недели выключен')
    if enabled:
        await callback.message.answer(
            'Раз в неделю бот создаст план по сигналам ниши. Будет списан один лимит контент-плана, '
            'и только если AI успешно подготовит результат.'
        )
    await _show_competitor_sources(callback.message, int(user['id']), product_repository, settings)


@router.callback_query(F.data == 'analysis:pulse_now')
async def competitor_pulse_now(
    callback: CallbackQuery,
    queries: QueryService,
    competitor_service: CompetitorMonitoringService,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    await callback.answer('Собираю Пульс ниши')
    await callback.message.answer('Анализирую публикации источников за последние 7 дней…')
    try:
        result = await competitor_service.build_pulse(int(user['id']))
    except ValueError as exc:
        await callback.message.answer(escape_html(str(exc)))
        return
    except Exception:
        await callback.message.answer('Не удалось собрать Пульс ниши. Попробуйте позже.')
        return
    await _send_model_text(callback.message, result, competitor_digest_keyboard())


@router.callback_query(F.data == 'analysis:competitor_plan_now')
async def competitor_plan_now(
    callback: CallbackQuery,
    queries: QueryService,
    competitor_service: CompetitorMonitoringService,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    await callback.answer('Собираю план')
    await callback.message.answer('Готовлю оригинальный план на 7 дней по сигналам ниши…')
    try:
        draft = await competitor_service.build_weekly_plan(int(user['id']))
    except AccessRequiredError:
        await _deny_access(callback)
        return
    except ValueError as exc:
        await callback.message.answer(escape_html(str(exc)))
        return
    except Exception:
        await callback.message.answer('Не удалось собрать план. Лимит не списан, попробуйте позже.')
        return
    await _send_model_text(
        callback.message,
        str(draft['content_text']),
        draft_actions_keyboard(int(draft['id'])),
    )


@router.callback_query(F.data == 'analysis:expert')
async def expert_review_menu(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    limits = await queries.get_user_limits(int(user['id'])) if user else {}
    post_available = int(limits.get('manual_post_reviews_left') or 0) > 0
    channel_available = int(limits.get('channel_reviews_left') or 0) > 0
    if not post_available and not channel_available:
        await callback.answer('Ручные разборы закончились', show_alert=True)
        return
    await callback.message.answer(
        '<b>Проверка специалистом</b>\n\nМатериал посмотрит человек. Ответ придёт в бот в течение дня.',
        reply_markup=expert_review_keyboard(channel_available, post_available),
    )
    await callback.answer()


@router.callback_query(F.data == 'analysis:expert_post')
async def expert_post_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await state.clear()
        await state.set_state(AnalysisStates.expert_post)
        await callback.message.answer('Пришлите пост и вопрос, на который особенно важно ответить.')
    await callback.answer()


@router.message(AnalysisStates.expert_post, F.text | F.caption)
async def expert_post_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    content = (message.text or message.caption or '').strip()
    consumed = await queries.consume_limit(int(user['id']), 'manual_post_reviews_left') if user else False
    if not consumed:
        await state.clear()
        await message.answer('Лимит ручных разборов поста закончился.')
        return
    try:
        request_id = await queries.create_manual_review_request(int(user['id']), 'post_review', content)
    except Exception:
        await queries.add_user_limits(int(user['id']), {'manual_post_reviews_left': 1})
        raise
    await state.clear()
    await product_repository.log_activity(
        'expert_review_requested',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        payload={'request_id': request_id, 'type': 'post_review'},
    )
    await message.answer(
        f'<b>Заявка #{request_id} принята.</b>\n\nСпециалист проверит пост и ответит здесь в течение дня.'
    )


@router.callback_query(F.data == 'analysis:expert_channel')
async def expert_channel_received(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not channel:
        await callback.answer('Сначала подключите канал', show_alert=True)
        return
    consumed = await queries.consume_limit(int(user['id']), 'channel_reviews_left')
    if not consumed:
        await callback.answer('Лимит ручных разборов канала закончился', show_alert=True)
        return
    posts = await product_repository.list_channel_posts(int(channel['id']), 20)
    content = (
        f"Канал: {channel['title']} (@{channel.get('username') or 'private'})\n\n"
        + '\n\n---\n\n'.join(str(item.get('content_text') or '') for item in posts)
    )
    try:
        request_id = await queries.create_manual_review_request(int(user['id']), 'channel_review', content)
    except Exception:
        await queries.add_user_limits(int(user['id']), {'channel_reviews_left': 1})
        raise
    await product_repository.log_activity(
        'expert_review_requested',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        payload={'request_id': request_id, 'type': 'channel_review'},
    )
    await callback.message.answer(
        f'<b>Заявка #{request_id} принята.</b>\n\nСпециалист проверит канал и ответит здесь в течение дня.'
    )
    await callback.answer('Заявка отправлена')


@router.callback_query(F.data == 'analysis:posts')
async def posts_analysis_start(callback: CallbackQuery, state: FSMContext, queries: QueryService) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.update_data(posts=[])
    await state.set_state(AnalysisStates.collecting_posts)
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    access_note = (
        'Первый такой разбор бесплатный.'
        if user and not user.get('used_free_analysis')
        else 'Бесплатный разбор уже использован; новый разбор спишет одно AI-действие.'
    )
    await callback.message.answer(
        '<b>Пришлите пост для разбора.</b>\n\nМожно добавить до 5 постов: я найду как сильные стороны, '
        f'так и общие точки роста. {access_note}'
    )
    await callback.answer()


@router.message(AnalysisStates.collecting_posts, F.text | F.caption)
async def collect_post(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    posts = list(data.get('posts') or [])
    if len(posts) >= 5:
        await message.answer('Уже собрано 5 постов. Запустите разбор.', reply_markup=analysis_collect_keyboard(5))
        return
    posts.append((message.text or message.caption or '').strip())
    await state.update_data(posts=posts)
    await message.answer(
        f"Постов собрано: <b>{len(posts)}</b>. Можно добавить ещё или начать разбор.",
        reply_markup=analysis_collect_keyboard(len(posts)),
    )


@router.callback_query(F.data == 'analysis:add')
async def add_post(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer('Пришлите следующий пост.')
    await callback.answer()


@router.callback_query(F.data == 'analysis:cancel')
async def cancel_analysis(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer('Разбор отменён.')
    await callback.answer()


@router.callback_query(F.data == 'analysis:run')
async def run_posts_analysis(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not callback.message:
        return
    data = await state.get_data()
    posts = [str(item).strip() for item in data.get('posts') or [] if str(item).strip()]
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user or not posts:
        await callback.answer('Сначала пришлите пост', show_alert=True)
        return
    is_free = not bool(user.get('used_free_analysis'))
    reservation = None
    if not is_free:
        reservation = await usage_service.reserve(int(user['id']), 'improve')
        if not reservation:
            await _deny_access(callback)
            return
    await callback.answer('Начинаю разбор')
    await callback.message.answer('Анализирую материал. Обычно это занимает меньше минуты…')
    combined = '\n\n--- СЛЕДУЮЩИЙ ПОСТ ---\n\n'.join(posts)
    try:
        result = await content_service.analyze_post(int(user['id']), combined, 'общая эффективность')
        analysis_id = await queries.add_analysis(
            user_id=int(user['id']),
            original_text=combined,
            post_goal='общая эффективность',
            result_text=result,
            is_free=is_free,
            posts_count=len(posts),
        )
        trial = await product_repository.get_trial(int(user['id']))
        keyboard = trial_offer_keyboard() if is_free and trial.get('status') == 'none' else None
        await _send_model_text(callback.message, result, keyboard)
        await queries.mark_analysis_delivered(analysis_id, int(user['id']))
    except Exception as exc:
        if reservation:
            await usage_service.refund(reservation)
        await callback.message.answer(f"<b>Не удалось выполнить разбор.</b>\n\n{escape_html(str(exc))}")
        return
    if reservation:
        await usage_service.commit(reservation)
    if is_free:
        await queries.set_free_analysis_used(int(user['id']))
    await product_repository.log_activity(
        'analysis_delivered',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'posts_count': len(posts), 'is_free': is_free},
    )
    await state.clear()


@router.callback_query(F.data == 'analysis:channel')
async def channel_analysis(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    if not settings.feature_channel_analysis:
        await callback.answer('Разбор канала временно выключен', show_alert=True)
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not channel:
        await callback.answer('Сначала подключите канал', show_alert=True)
        return
    posts = await product_repository.list_channel_posts(int(channel['id']), 20)
    texts = [str(item.get('content_text') or '').strip() for item in posts if str(item.get('content_text') or '').strip()]
    if len(texts) < 3:
        await callback.message.answer(
            '<b>Пока мало данных.</b>\n\nБот видит публикации только после подключения канала. '
            'Опубликуйте через KonturSMM или дождитесь хотя бы трёх новых постов.'
        )
        await callback.answer()
        return
    reservation = await usage_service.reserve(int(user['id']), 'channel_analysis')
    if not reservation:
        await _deny_access(callback)
        return
    await callback.answer('Анализирую канал')
    try:
        result = await content_service.analyze_channel(int(user['id']), texts)
        await _send_model_text(callback.message, result)
    except Exception as exc:
        await usage_service.refund(reservation)
        await callback.message.answer(f"Не удалось разобрать канал: {escape_html(str(exc))}")
        return
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'channel_analysis_delivered',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        payload={'posts_count': len(texts)},
    )


@router.callback_query(F.data == 'analysis:intercept')
async def intercept_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.set_state(AnalysisStates.intercept_post)
    await callback.message.answer(
        '<b>Перехват темы</b>\n\nПерешлите или вставьте интересный пост. Я не буду его копировать, '
        'а найду оригинальные углы для вашего канала.'
    )
    await callback.answer()


@router.message(AnalysisStates.intercept_post, F.text | F.caption)
async def intercept_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    reservation = await usage_service.reserve(int(user['id']), 'topic_intercept')
    if not reservation:
        await state.clear()
        await _deny_access(message)
        return
    try:
        source_text = (message.text or message.caption or '').strip()
        result = await content_service.intercept_topic(int(user['id']), source_text)
        channel = await product_repository.get_active_channel(int(user['id']))
        draft = await product_repository.create_draft(
            user_id=int(user['id']),
            channel_id=int(channel['id']) if channel else None,
            source_type='topic_intercept',
            source_text=source_text,
            content_text=result,
            ai_mode='ideas',
        )
        await _send_model_text(message, result)
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"Не удалось разобрать тему: {escape_html(str(exc))}")
        return
    finally:
        await state.clear()
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'topic_intercept_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        payload={'draft_id': int(draft['id'])},
    )


@router.callback_query(F.data.startswith('analysis:intercept_saved:'))
async def intercept_saved_competitor_post(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    post_id = int(callback.data.rsplit(':', 1)[1])
    post = await product_repository.get_competitor_post(post_id, int(user['id'])) if user else None
    if not user or not post:
        await callback.answer('Публикация не найдена', show_alert=True)
        return
    source_text = str(post.get('content_text') or '').strip()
    if not source_text:
        await callback.answer('В этой публикации нет текста для перехвата', show_alert=True)
        return
    reservation = await usage_service.reserve(int(user['id']), 'topic_intercept')
    if not reservation:
        await _deny_access(callback)
        return
    await callback.answer('Ищу оригинальные углы')
    await callback.message.answer('Разбираю тему без копирования формулировок и структуры…')
    try:
        result = await content_service.intercept_topic(int(user['id']), source_text)
        channel = await product_repository.get_active_channel(int(user['id']))
        draft = await product_repository.create_draft(
            user_id=int(user['id']),
            channel_id=int(channel['id']) if channel else None,
            source_type='competitor_radar',
            source_text=source_text,
            content_text=result,
            ai_mode='ideas',
        )
    except Exception as exc:
        await usage_service.refund(reservation)
        await callback.message.answer(f'Не удалось перехватить тему: {escape_html(str(exc))}')
        return
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'topic_intercept_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'draft_id': int(draft['id']), 'competitor_post_id': post_id},
    )
    await _send_model_text(
        callback.message,
        result,
        draft_actions_keyboard(int(draft['id'])),
    )
