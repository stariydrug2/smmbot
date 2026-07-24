from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import Settings
from database.queries import QueryService
from keyboards.inline import (
    after_analysis_keyboard,
    analysis_collect_keyboard,
    analysis_goal_keyboard,
    content_plan_period_keyboard,
    cta_type_keyboard,
    free_analysis_keyboard,
    history_keyboard,
    image_style_keyboard,
    limit_exhausted_keyboard,
    payment_plans_keyboard,
    post_actions_keyboard,
    post_goal_keyboard,
    profile_keyboard,
    premium_request_keyboard,
    style_keyboard,
)
from keyboards.reply import main_menu_keyboard
from services.content_service import ContentService
from services.image_service import ImageService
from services.subscription_service import SubscriptionService
from states.generation_states import GenerationStates
from utils.formatting import format_history, format_profile
from utils.helpers import ensure_dir, escape_html, render_model_text, truncate
from utils.texts import HELP_TEXT, MENU_TEXT, PAYMENT_MENU_TEXT

router = Router()

MAX_ANALYSIS_POSTS = 5
MAX_ANALYSIS_CHARS = 12000

MENU_TEXTS = {
    '🔎 Проверить пост бесплатно',
    '✍️ Создать пост',
    '⚡ Улучшить мой пост',
    '📌 Сделать CTA',
    '🗓 Контент-план',
    '💡 Идеи',
    '🎙 Голос → пост',
    '🖼 Изображение к посту',
    '📊 Мои лимиты',
    '💳 Тарифы',
    '👤 Личный кабинет',
    '🕘 История',
    '🧑‍💻 Поддержка',
    '⬅️ Назад',
}

GOAL_LABELS = {
    'sale': 'продажа',
    'warmup': 'прогрев',
    'expertise': 'экспертность',
    'engagement': 'вовлечение',
    'improve': 'просто улучшить текст',
    'personal': 'личный пост',
    'announce': 'анонс',
}

STYLE_LABELS = {
    'expert': 'экспертно',
    'simple': 'живее и проще',
    'sales': 'продающе',
    'bold': 'провокационнее',
    'short': 'короче',
    'details': 'подробнее',
}

LIMIT_LABELS = {
    'posts_left': 'посты',
    'cta_left': 'CTA',
    'ideas_left': 'идеи',
    'improvements_left': 'улучшения',
    'images_left': 'изображения',
    'voice_posts_left': 'голос → пост',
    'content_plans_left': 'контент-планы',
    'channel_reviews_left': 'ручные разборы канала',
    'manual_post_reviews_left': 'ручные разборы постов',
}


async def _current_user(message_or_callback: Message | CallbackQuery, queries: QueryService) -> dict[str, Any] | None:
    from_user = message_or_callback.from_user
    if not from_user:
        return None
    user = await queries.get_user_by_telegram_id(from_user.id)
    return user


async def _has_limit(user: dict[str, Any], queries: QueryService, field: str) -> bool:
    if bool(user.get('is_admin')):
        return True
    return await queries.has_limit(int(user['id']), field)


async def _consume_limit(user: dict[str, Any], queries: QueryService, field: str) -> None:
    if bool(user.get('is_admin')):
        return
    await queries.consume_limit(int(user['id']), field)


async def _send_limit_exhausted(target: Message | CallbackQuery, field: str) -> None:
    text = (
        '<b>Лимит по этой функции закончился.</b>\n\n'
        f"Функция: {escape_html(LIMIT_LABELS.get(field, field))}\n\n"
        'Можно докупить пакет или перейти на тариф выше.'
    )
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.answer(text, reply_markup=limit_exhausted_keyboard())
        await target.answer('Лимит закончился', show_alert=True)
        return
    await target.answer(text, reply_markup=limit_exhausted_keyboard())


def _clean_text(text: str | None, *, max_len: int = 6000) -> str:
    value = (text or '').strip()
    if len(value) > max_len:
        return value[:max_len].rstrip()
    return value


def _format_analysis_posts(posts: list[str]) -> str:
    cleaned = [post.strip() for post in posts if post and post.strip()]
    if not cleaned:
        return ''
    if len(cleaned) == 1:
        return cleaned[0]
    return '\n\n'.join(f'Пост {index}:\n{text}' for index, text in enumerate(cleaned, start=1))


def _analysis_collect_text(posts_count: int) -> str:
    if posts_count >= MAX_ANALYSIS_POSTS:
        return (
            f'<b>Добавил пост. Сейчас в подборке: {posts_count}.</b>\n\n'
            'Этого достаточно для хорошего общего разбора. Нажми «Разобрать сейчас», чтобы выбрать цель и запустить анализ.'
        )
    if posts_count == 1:
        return (
            '<b>Пост добавлен.</b>\n\n'
            'Можно разобрать его сейчас или прислать ещё один пост, если хочешь анализ по нескольким материалам сразу.'
        )
    return (
        f'<b>Пост добавлен. Сейчас в подборке: {posts_count}.</b>\n\n'
        'Можешь прислать ещё один пост или запустить общий разбор текущей подборки.'
    )


async def _append_analysis_post(state: FSMContext, text: str) -> tuple[list[str], str | None]:
    data = await state.get_data()
    posts = [str(post).strip() for post in data.get('analysis_posts') or [] if str(post).strip()]
    previous_text = str(data.get('analysis_text') or '').strip()
    if not posts and previous_text:
        posts.append(previous_text)
    if len(posts) >= MAX_ANALYSIS_POSTS:
        return posts, 'max_posts'

    remaining_chars = MAX_ANALYSIS_CHARS - sum(len(post) for post in posts)
    if remaining_chars <= 0:
        return posts, 'max_chars'

    post = text.strip()
    if len(post) > remaining_chars:
        post = post[:remaining_chars].rstrip()
    posts.append(post)
    await state.update_data(analysis_posts=posts, analysis_text=_format_analysis_posts(posts))
    return posts, None


def _extract_score(text: str) -> int | None:
    match = re.search(r'оценка\s*:\s*(\d{1,2})\s*/\s*10', text, flags=re.IGNORECASE)
    if not match:
        return None
    return max(0, min(10, int(match.group(1))))


@router.message(F.text.in_(MENU_TEXTS))
async def main_menu_shortcut(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    settings: Settings,
    subscription_service: SubscriptionService,
) -> None:
    text = (message.text or '').strip()
    is_admin = bool(message.from_user and message.from_user.id in settings.admin_ids)

    if text == '⬅️ Назад':
        await state.clear()
        await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=is_admin))
        return

    if text == '🧑‍💻 Поддержка':
        await state.clear()
        await message.answer(HELP_TEXT.format(support_username=escape_html(settings.normalized_support_username)))
        return

    user = await _current_user(message, queries)
    if not user:
        return

    await state.clear()

    if text == '🔎 Проверить пост бесплатно':
        await _start_free_analysis(message, state, user)
        return
    if text == '✍️ Создать пост':
        await create_post_entry(message, state, queries)
        return
    if text == '⚡ Улучшить мой пост':
        await improve_entry(message, state, queries)
        return
    if text == '📌 Сделать CTA':
        await cta_entry(message, state, queries)
        return
    if text == '🗓 Контент-план':
        await plan_entry(message, state, queries)
        return
    if text == '💡 Идеи':
        await ideas_entry(message, state, queries)
        return
    if text == '🎙 Голос → пост':
        await voice_to_post_entry(message, state, queries)
        return
    if text == '🖼 Изображение к посту':
        await image_entry(message, state, queries)
        return
    if text == '📊 Мои лимиты':
        await limits_entry(message, queries)
        return
    if text == '💳 Тарифы':
        plans = await queries.get_subscription_plans()
        payment_text = PAYMENT_MENU_TEXT
        if user.get('current_tariff'):
            payment_text += (
                f"\n\n<b>Текущий тариф:</b> {escape_html(str(user.get('current_tariff')))}"
                f"\n<b>Действует до:</b> {escape_html(str(user.get('tariff_expires_at') or '—'))}"
            )
        await message.answer(payment_text, reply_markup=payment_plans_keyboard(plans))
        return
    if text == '👤 Личный кабинет':
        profile = await queries.get_brand_profile(user['id'])
        summary = await queries.get_memory_summary(user['id'])
        history = await queries.get_generation_history(user['id'], limit=100)
        status = await subscription_service.get_status(user['id'])
        last_payments = await queries.list_user_payments(user['id'], limit=3)
        await message.answer(format_profile(profile, user, summary, len(history), status, last_payments), reply_markup=profile_keyboard())
        return
    if text == '🕘 История':
        records = await queries.get_generation_history(user['id'], limit=15)
        await message.answer(format_history(records), reply_markup=history_keyboard(records))


@router.callback_query(lambda c: c.data == 'analysis:start')
async def free_analysis_callback(callback: CallbackQuery, state: FSMContext, queries: QueryService) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    await _start_free_analysis(callback.message, state, user)
    await callback.answer()


@router.message(F.text == '🔎 Проверить пост бесплатно')
async def free_analysis_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    await _start_free_analysis(message, state, user)


async def _start_free_analysis(message: Message, state: FSMContext, user: dict[str, Any]) -> None:
    if bool(user.get('used_free_analysis')):
        await message.answer(
            '<b>Бесплатный анализ уже использован.</b>\n\n'
            'Я могу улучшить твой пост или сделать новый контент по тарифу.',
            reply_markup=after_analysis_keyboard(),
        )
        return
    await state.set_state(GenerationStates.waiting_for_free_analysis_text)
    await state.update_data(analysis_posts=[], analysis_text='', last_analysis_posts_count=0)
    await message.answer(
        '<b>Пришли текст поста, который хочешь проверить.</b>\n\n'
        'Можно отправить один пост или несколько постов подряд. Когда материалов будет достаточно, нажми «Разобрать сейчас».\n\n'
        'Я разберу: что уже работает, где теряется внимание, понятна ли мысль, хочется ли дочитать и работает ли CTA.'
    )


@router.message(
    StateFilter(None),
    F.text.func(lambda text: bool(text and len(text.strip()) >= 120 and text.strip() not in MENU_TEXTS and not text.strip().startswith('/'))),
)
async def direct_text_as_free_analysis(message: Message, state: FSMContext, queries: QueryService) -> None:
    text = _clean_text(message.text)
    if not message.from_user or not text or text in MENU_TEXTS or text.startswith('/'):
        return
    if len(text) < 120:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    if bool(user.get('used_free_analysis')):
        await message.answer(
            '<b>Похоже, ты прислал пост.</b>\n\n'
            'Бесплатный анализ уже использован. Можно улучшить текст по тарифу или купить пакет.',
            reply_markup=after_analysis_keyboard(),
        )
        return
    await state.update_data(analysis_posts=[], analysis_text='', last_analysis_posts_count=0)
    posts, _ = await _append_analysis_post(state, text)
    await state.set_state(GenerationStates.waiting_for_free_analysis_text)
    await message.answer(_analysis_collect_text(len(posts)), reply_markup=analysis_collect_keyboard(len(posts)))


@router.message(GenerationStates.waiting_for_free_analysis_text)
async def free_analysis_text(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text)
    if not text:
        await message.answer('Нужен именно текст поста. Пришли его сообщением.')
        return
    if len(text) < 40:
        await message.answer('Текст слишком короткий для нормального анализа. Пришли полноценный пост.')
        return
    posts, issue = await _append_analysis_post(state, text)
    if issue:
        await message.answer(
            '<b>Материалов уже достаточно для разбора.</b>\n\n'
            'Нажми «Разобрать сейчас», чтобы выбрать цель и запустить анализ.',
            reply_markup=analysis_collect_keyboard(len(posts)),
        )
        return
    await state.set_state(GenerationStates.waiting_for_free_analysis_text)
    await message.answer(_analysis_collect_text(len(posts)), reply_markup=analysis_collect_keyboard(len(posts)))


@router.callback_query(lambda c: c.data == 'analysis:add_more')
async def analysis_add_more(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.set_state(GenerationStates.waiting_for_free_analysis_text)
    await callback.message.answer(
        'Ок, пришли следующий пост отдельным сообщением. Когда закончишь, нажми «Разобрать сейчас».'
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == 'analysis:choose_goal')
async def analysis_choose_goal(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    data = await state.get_data()
    posts = [str(post).strip() for post in data.get('analysis_posts') or [] if str(post).strip()]
    if not posts:
        await state.set_state(GenerationStates.waiting_for_free_analysis_text)
        await callback.message.answer('Пришли текст поста для анализа.')
        await callback.answer()
        return
    await state.update_data(analysis_text=_format_analysis_posts(posts))
    await state.set_state(GenerationStates.waiting_for_analysis_goal)
    if len(posts) > 1:
        await callback.message.answer('<b>Какая общая цель у этих постов?</b>', reply_markup=analysis_goal_keyboard())
    else:
        await callback.message.answer('<b>Какая цель у этого поста?</b>', reply_markup=analysis_goal_keyboard())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('analysis_goal:'))
async def free_analysis_goal(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
    settings: Settings,
) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    if bool(user.get('used_free_analysis')):
        await callback.message.answer('<b>Бесплатный анализ уже использован.</b>', reply_markup=after_analysis_keyboard())
        await callback.answer()
        return
    data = await state.get_data()
    posts = [str(post).strip() for post in data.get('analysis_posts') or [] if str(post).strip()]
    post_text = _format_analysis_posts(posts) if posts else str(data.get('analysis_text') or '').strip()
    if not post_text:
        await state.set_state(GenerationStates.waiting_for_free_analysis_text)
        await callback.message.answer('Пришли текст поста для анализа.')
        await callback.answer()
        return
    goal = GOAL_LABELS.get(callback.data.split(':', maxsplit=1)[1], 'просто улучшить текст')
    await callback.answer('Анализирую посты...' if len(posts) > 1 else 'Анализирую пост...')
    try:
        result = await content_service.analyze_post(int(user['id']), post_text, goal)
    except RuntimeError:
        await callback.message.answer(
            '<b>Не получилось обработать запрос.</b>\n\n'
            'Бесплатный анализ не списан. Попробуй ещё раз или напиши в поддержку.'
        )
        return

    await queries.add_analysis(int(user['id']), post_text, goal, result, score=_extract_score(result), is_free=True)
    await queries.set_free_analysis_used(int(user['id']), True)
    await state.update_data(
        last_analyzed_post=post_text if len(posts) <= 1 else '',
        last_analysis_posts_count=max(1, len(posts)),
    )
    await state.set_state(GenerationStates.waiting_for_options)
    await callback.message.answer(f"<b>Разбор готов.</b>\n\n{render_model_text(result)}")
    if settings.channel_link:
        await callback.message.answer(
            f'Если хочешь следить за обновлениями KonturSMM, можно подписаться на канал: {escape_html(settings.channel_link)}'
        )
    await callback.message.answer(
        '<b>Я могу не только показать слабые места, но и полностью усилить этот пост:</b>\n'
        '• переписать начало\n'
        '• убрать воду\n'
        '• выстроить структуру\n'
        '• добавить сильный CTA\n'
        '• сделать текст живее\n\n'
        'Для этого подойдет тариф “Старт”.',
        reply_markup=after_analysis_keyboard(),
    )


@router.callback_query(lambda c: c.data == 'product:improve_last')
async def improve_last_post(callback: CallbackQuery, state: FSMContext, queries: QueryService) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'improvements_left'):
        await _send_limit_exhausted(callback, 'improvements_left')
        return
    data = await state.get_data()
    if int(data.get('last_analysis_posts_count') or 1) > 1:
        await state.set_state(GenerationStates.waiting_for_improvement_text)
        await callback.message.answer(
            'В разборе было несколько постов. Пришли один конкретный текст, который нужно улучшить.'
        )
        await callback.answer()
        return
    post_text = str(data.get('last_analyzed_post') or '').strip()
    if not post_text:
        await state.set_state(GenerationStates.waiting_for_improvement_text)
        await callback.message.answer('Пришли текст поста, который нужно улучшить.')
        await callback.answer()
        return
    await state.update_data(improvement_text=post_text)
    await state.set_state(GenerationStates.waiting_for_improvement_style)
    await callback.message.answer('<b>В каком стиле улучшить пост?</b>', reply_markup=style_keyboard('improve_style'))
    await callback.answer()


@router.message(F.text == '⚡ Улучшить мой пост')
async def improve_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'improvements_left'):
        await _send_limit_exhausted(message, 'improvements_left')
        return
    await state.set_state(GenerationStates.waiting_for_improvement_text)
    await message.answer('<b>Пришли текст поста, который нужно усилить.</b>')


@router.message(GenerationStates.waiting_for_improvement_text)
async def improve_text(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text)
    if len(text) < 40:
        await message.answer('Пришли более полный текст поста.')
        return
    await state.update_data(improvement_text=text)
    await state.set_state(GenerationStates.waiting_for_improvement_style)
    await message.answer('<b>В каком стиле улучшить пост?</b>', reply_markup=style_keyboard('improve_style'))


@router.callback_query(lambda c: c.data and c.data.startswith('improve_style:'))
async def improve_style(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'improvements_left'):
        await _send_limit_exhausted(callback, 'improvements_left')
        return
    data = await state.get_data()
    text = str(data.get('improvement_text') or '').strip()
    style = STYLE_LABELS.get(callback.data.split(':', maxsplit=1)[1], 'живее и проще')
    await callback.answer('Улучшаю пост...')
    try:
        result = await content_service.generate(
            user_id=int(user['id']),
            mode='rewrite',
            user_request=text,
            source_type='text',
            style=style,
        )
    except RuntimeError:
        await callback.message.answer('<b>Не получилось обработать запрос.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'improvements_left')
    await state.update_data(last_result=result, original_request=text, mode='rewrite')
    await callback.message.answer(f"<b>Пост усилен.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


@router.message(F.text == '✍️ Создать пост')
@router.callback_query(lambda c: c.data == 'product:create_post')
async def create_post_entry(event: Message | CallbackQuery, state: FSMContext, queries: QueryService) -> None:
    message = event.message if isinstance(event, CallbackQuery) else event
    if not message:
        return
    user = await _current_user(event, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'posts_left'):
        await _send_limit_exhausted(event, 'posts_left')
        return
    await state.set_state(GenerationStates.waiting_for_new_post_topic)
    await message.answer('<b>О чем сделать пост?</b>\n\nПришли тему, тезисы или короткий бриф.')
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(GenerationStates.waiting_for_new_post_topic)
async def new_post_topic(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text)
    if len(text) < 5:
        await message.answer('Напиши тему или пару тезисов для поста.')
        return
    await state.update_data(post_topic=text)
    await state.set_state(GenerationStates.waiting_for_new_post_goal)
    await message.answer('<b>Какая цель у поста?</b>', reply_markup=post_goal_keyboard('post_goal'))


@router.callback_query(lambda c: c.data and c.data.startswith('post_goal:'))
async def new_post_goal(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    goal = GOAL_LABELS.get(callback.data.split(':', maxsplit=1)[1], 'экспертность')
    await state.update_data(post_goal=goal)
    await state.set_state(GenerationStates.waiting_for_new_post_tone)
    await callback.message.answer('<b>Какой нужен тон?</b>', reply_markup=style_keyboard('post_tone'))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('post_tone:'))
async def new_post_tone(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'posts_left'):
        await _send_limit_exhausted(callback, 'posts_left')
        return
    data = await state.get_data()
    topic = str(data.get('post_topic') or '')
    goal = str(data.get('post_goal') or '')
    tone = STYLE_LABELS.get(callback.data.split(':', maxsplit=1)[1], 'живой')
    await callback.answer('Создаю пост...')
    try:
        result = await content_service.generate(
            user_id=int(user['id']),
            mode='post',
            user_request=topic,
            source_type='text',
            goal=goal,
            tone=tone,
            length='средне',
        )
    except RuntimeError:
        await callback.message.answer('<b>Не получилось создать пост.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'posts_left')
    await state.update_data(last_result=result, original_request=topic, mode='post')
    await callback.message.answer(f"<b>Пост готов.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


@router.message(F.text == '📌 Сделать CTA')
async def cta_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'cta_left'):
        await _send_limit_exhausted(message, 'cta_left')
        return
    await state.set_state(GenerationStates.waiting_for_cta_text)
    await message.answer('<b>Пришли пост или кратко опиши цель CTA.</b>')


@router.message(GenerationStates.waiting_for_cta_text)
async def cta_text(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text)
    if len(text) < 5:
        await message.answer('Нужен пост или понятная цель CTA.')
        return
    await state.update_data(cta_text=text)
    await state.set_state(GenerationStates.waiting_for_cta_type)
    await message.answer('<b>Какой тип CTA нужен?</b>', reply_markup=cta_type_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith('cta_type:'))
async def cta_type(callback: CallbackQuery, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'cta_left'):
        await _send_limit_exhausted(callback, 'cta_left')
        return
    data = await state.get_data()
    cta_source = str(data.get('cta_text') or '')
    cta_kind = callback.data.split(':', maxsplit=1)[1]
    await callback.answer('Готовлю CTA...')
    try:
        result = await content_service.generate(
            user_id=int(user['id']),
            mode='cta',
            user_request=cta_source,
            source_type='text',
            cta_type=cta_kind,
        )
    except RuntimeError:
        await callback.message.answer('<b>Не получилось создать CTA.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'cta_left')
    await state.update_data(last_result=result, original_request=cta_source, mode='cta')
    await callback.message.answer(f"<b>CTA готовы.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


@router.message(F.text == '💡 Идеи')
async def ideas_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'ideas_left'):
        await _send_limit_exhausted(message, 'ideas_left')
        return
    await state.set_state(GenerationStates.waiting_for_ideas_topic)
    await message.answer('<b>Для какой темы или ниши придумать идеи постов?</b>')


@router.message(GenerationStates.waiting_for_ideas_topic)
async def ideas_topic(message: Message, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'ideas_left'):
        await _send_limit_exhausted(message, 'ideas_left')
        return
    topic = _clean_text(message.text)
    if len(topic) < 5:
        await message.answer('Напиши тему или нишу чуть подробнее.')
        return
    try:
        result = await content_service.generate(int(user['id']), 'ideas', topic, source_type='text')
    except RuntimeError:
        await message.answer('<b>Не получилось придумать идеи.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'ideas_left')
    await state.update_data(last_result=result, original_request=topic, mode='ideas')
    await message.answer(f"<b>Идеи готовы.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


@router.message(F.text == '🗓 Контент-план')
async def plan_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'content_plans_left'):
        await _send_limit_exhausted(message, 'content_plans_left')
        return
    await state.set_state(GenerationStates.waiting_for_plan_niche)
    await message.answer('<b>Для какой ниши или проекта сделать контент-план?</b>')


@router.message(GenerationStates.waiting_for_plan_niche)
async def plan_niche(message: Message, state: FSMContext) -> None:
    niche = _clean_text(message.text)
    if len(niche) < 5:
        await message.answer('Опиши нишу или проект чуть подробнее.')
        return
    await state.update_data(plan_niche=niche)
    await state.set_state(GenerationStates.waiting_for_plan_goal)
    await message.answer('<b>Какая цель плана?</b>', reply_markup=post_goal_keyboard('plan_goal'))


@router.callback_query(lambda c: c.data and c.data.startswith('plan_goal:'))
async def plan_goal(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    goal = GOAL_LABELS.get(callback.data.split(':', maxsplit=1)[1], 'регулярность')
    await state.update_data(plan_goal=goal)
    await state.set_state(GenerationStates.waiting_for_plan_period)
    await callback.message.answer('<b>На какой период сделать план?</b>', reply_markup=content_plan_period_keyboard())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('plan_period:'))
async def plan_period(callback: CallbackQuery, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'content_plans_left'):
        await _send_limit_exhausted(callback, 'content_plans_left')
        return
    data = await state.get_data()
    period = callback.data.split(':', maxsplit=1)[1]
    brief = f"Ниша: {data.get('plan_niche')}\nЦель: {data.get('plan_goal')}\nПериод: {period} дней"
    await callback.answer('Собираю контент-план...')
    try:
        result = await content_service.generate(int(user['id']), 'content_plan', brief, source_type='text', period=f'{period} дней')
    except RuntimeError:
        await callback.message.answer('<b>Не получилось создать контент-план.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'content_plans_left')
    await state.update_data(last_result=result, original_request=brief, mode='content_plan')
    await callback.message.answer(f"<b>Контент-план готов.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


@router.message(F.text == '🖼 Изображение к посту')
async def image_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'images_left'):
        await _send_limit_exhausted(message, 'images_left')
        return
    await state.set_state(GenerationStates.waiting_for_image_text)
    await message.answer('<b>Пришли пост или опиши тему изображения.</b>')


@router.message(F.text == '🎙 Голос → пост')
async def voice_to_post_entry(message: Message, state: FSMContext, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    if not await _has_limit(user, queries, 'voice_posts_left'):
        await _send_limit_exhausted(message, 'voice_posts_left')
        return
    await state.set_state(GenerationStates.waiting_for_voice)
    await message.answer('<b>Отправь голосовое или аудиофайл.</b>\n\nПосле распознавания я предложу сделать из него пост.')


@router.message(GenerationStates.waiting_for_image_text)
async def image_text(message: Message, state: FSMContext) -> None:
    text = _clean_text(message.text)
    if len(text) < 5:
        await message.answer('Опиши изображение или пришли пост.')
        return
    await state.update_data(image_text=text)
    await state.set_state(GenerationStates.waiting_for_image_style)
    await message.answer('<b>В каком стиле сделать изображение?</b>', reply_markup=image_style_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith('image_style:'))
async def image_style(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
    image_service: ImageService,
) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    if not await _has_limit(user, queries, 'images_left'):
        await _send_limit_exhausted(callback, 'images_left')
        return
    data = await state.get_data()
    source_text = str(data.get('image_text') or '')
    style = callback.data.split(':', maxsplit=1)[1]
    await callback.answer('Генерирую изображение...')
    try:
        prompt_result = await content_service.generate(
            int(user['id']),
            'image_prompt',
            source_text,
            source_type='text',
            style=style,
        )
        final_prompt = prompt_result.strip().splitlines()[-1].strip()
        out_dir = ensure_dir(Path('tmp/images'))
        out_path = out_dir / f'{uuid.uuid4()}.png'
        try:
            image_path = await image_service.generate_image(final_prompt, out_path)
            await callback.message.answer_photo(
                photo=BufferedInputFile(image_path.read_bytes(), filename=image_path.name),
                caption=f"<b>Изображение готово.</b>\n\n<b>Промпт:</b> {escape_html(truncate(final_prompt, 800))}",
            )
        finally:
            out_path.unlink(missing_ok=True)
    except RuntimeError:
        await callback.message.answer('<b>Не получилось сгенерировать изображение.</b>\n\nЛимит не списан. Попробуй ещё раз.')
        return
    await _consume_limit(user, queries, 'images_left')


@router.message(F.text == '📊 Мои лимиты')
async def limits_entry(message: Message, queries: QueryService) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    limits = await queries.get_user_limits(int(user['id']))
    text = _format_limits(user, limits)
    keyboard = premium_request_keyboard(limits) if (
        int(limits.get('channel_reviews_left') or 0) > 0 or int(limits.get('manual_post_reviews_left') or 0) > 0
    ) else None
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == 'payment:manage')
async def tariffs_callback(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.message:
        return
    plans = await queries.get_subscription_plans()
    await callback.message.answer(PAYMENT_MENU_TEXT, reply_markup=payment_plans_keyboard(plans))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('premium_request:'))
async def premium_request_start(callback: CallbackQuery, state: FSMContext, queries: QueryService) -> None:
    if not callback.message:
        return
    user = await _current_user(callback, queries)
    if not user:
        await callback.answer()
        return
    request_type = callback.data.split(':', maxsplit=1)[1]
    field = 'channel_reviews_left' if request_type == 'channel_review' else 'manual_post_reviews_left'
    if not await _has_limit(user, queries, field):
        await _send_limit_exhausted(callback, field)
        return
    await state.update_data(manual_review_type=request_type, manual_review_limit=field)
    await state.set_state(GenerationStates.waiting_for_manual_review_content)
    await callback.message.answer(
        '<b>Пришли материал для ручного разбора.</b>\n\n'
        'Для канала можно отправить ссылку. Для поста - текст поста. '
        'Специалист проверит и мы дадим ответ в течение дня.'
    )
    await callback.answer()


@router.message(GenerationStates.waiting_for_manual_review_content)
async def premium_request_content(message: Message, state: FSMContext, queries: QueryService, settings: Settings) -> None:
    user = await _current_user(message, queries)
    if not user:
        return
    data = await state.get_data()
    request_type = str(data.get('manual_review_type') or 'post_review')
    field = str(data.get('manual_review_limit') or 'manual_post_reviews_left')
    if not await _has_limit(user, queries, field):
        await _send_limit_exhausted(message, field)
        return
    content = _clean_text(message.text, max_len=8000)
    if len(content) < 5:
        await message.answer('Пришли ссылку на канал или текст поста.')
        return
    request_id = await queries.create_manual_review_request(int(user['id']), request_type, content)
    await _consume_limit(user, queries, field)
    await queries.log_admin_event('INFO', 'premium_request_created', f'id={request_id} user_id={user["id"]}')
    await state.clear()
    await message.answer(
        '<b>Заявка принята.</b>\n\n'
        'Специалист проверит материал и мы дадим ответ в течение дня.',
        reply_markup=main_menu_keyboard(is_admin=bool(message.from_user and message.from_user.id in settings.admin_ids)),
    )
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                f'<b>Новая Premium-заявка #{request_id}</b>\n\n'
                f'Тип: {escape_html(request_type)}\n'
                f'Пользователь: <code>{user.get("telegram_id")}</code>\n\n'
                f'{escape_html(truncate(content, 1200))}\n\n'
                f'Ответить: <code>/reply_premium {request_id} текст ответа</code>',
            )
        except Exception:
            continue


def _format_limits(user: dict[str, Any], limits: dict[str, Any]) -> str:
    lines = [
        '<b>Мои лимиты</b>',
        '',
        f"<b>Текущий тариф:</b> {escape_html(str(user.get('current_tariff') or 'нет активного тарифа'))}",
        f"<b>Действует до:</b> {escape_html(str(user.get('tariff_expires_at') or '—'))}",
        '',
    ]
    for field, label in LIMIT_LABELS.items():
        lines.append(f"<b>{escape_html(label)}:</b> {int(limits.get(field) or 0)}")
    return '\n'.join(lines)
