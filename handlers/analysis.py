from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from handlers.content import _deny_access, _send_model_text
from keyboards.product import (
    analysis_collect_keyboard,
    competitor_sources_keyboard,
    expert_review_keyboard,
    trial_offer_keyboard,
)
from services.content_service import ContentService
from services.usage_service import UsageService
from states.product_states import AnalysisStates
from utils.helpers import escape_html

router = Router()


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
    sources = await product_repository.list_competitor_sources(int(user['id'])) if user else []
    lines = ['<b>Источники тем</b>', '']
    if sources:
        lines.extend(f"• {escape_html(str(item.get('source_url') or ''))}" for item in sources)
    else:
        lines.append('Список пока пуст.')
    if not settings.feature_competitor_monitoring:
        lines.append(
            '\nАвтоматическое чтение чужих каналов выключено: Telegram Bot API не даёт надёжно '
            'загружать их историю. Перешлите конкретный пост в «Перехват темы».'
        )
    await callback.message.answer('\n'.join(lines), reply_markup=competitor_sources_keyboard(sources))
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
) -> None:
    if not message.from_user:
        return
    raw = message.text.strip()
    username = raw.lstrip('@') if raw.startswith('@') else raw.rstrip('/').rsplit('/', 1)[-1]
    if not username or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for char in username):
        await message.answer('Не похоже на ссылку Telegram-канала. Пример: <code>https://t.me/channel</code>.')
        return
    source_url = f'https://t.me/{username}'
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    await product_repository.add_competitor_source(int(user['id']), username, source_url)
    await state.clear()
    await message.answer('Источник сохранён. Для анализа конкретной публикации используйте «Перехват темы».')


@router.callback_query(F.data.startswith('analysis:source_remove:'))
async def competitor_source_remove(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    source_id = int(callback.data.rsplit(':', 1)[1])
    removed = await product_repository.remove_competitor_source(source_id, int(user['id'])) if user else False
    await callback.answer('Источник удалён' if removed else 'Источник не найден', show_alert=not removed)


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
