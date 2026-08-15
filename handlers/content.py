from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from keyboards.product import access_required_keyboard, draft_actions_keyboard, drafts_keyboard
from services.content_service import ContentService
from services.image_service import ImageService
from services.publishing_service import PublishingService
from services.transcription_service import TranscriptionService
from services.usage_service import UsageService
from states.product_states import CreateStates
from utils.helpers import escape_html, render_model_text

router = Router()

MODE_INFO = {
    'post': ('post', 'Опишите тему, цель и факты, которые обязательно использовать.'),
    'ideas': ('ideas', 'Опишите нишу, задачу или тему, для которой нужны идеи.'),
    'rewrite': ('rewrite', 'Пришлите текст и коротко укажите, что в нём нужно изменить.'),
    'cta': ('cta', 'Пришлите пост или опишите действие, к которому нужно привести читателя.'),
}


async def _get_user(telegram_id: int, queries: QueryService) -> dict | None:
    return await queries.get_user_by_telegram_id(telegram_id)


async def _send_model_text(message: Message, text: str, reply_markup: object | None = None) -> None:
    rendered = render_model_text(text)
    chunks = PublishingService._split_text(rendered, limit=3900)
    for index, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=reply_markup if index == len(chunks) - 1 else None)


async def _deny_access(target: Message | CallbackQuery) -> None:
    text = (
        '<b>Для этого действия нужен доступ.</b>\n\n'
        'Можно один раз включить пробный режим на 24 часа и 5 AI-действий или выбрать тариф.'
    )
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.answer(text, reply_markup=access_required_keyboard())
        await target.answer('Нужен доступ', show_alert=True)
    else:
        await target.answer(text, reply_markup=access_required_keyboard())


async def _generate_draft(
    message: Message,
    user: dict,
    mode: str,
    request: str,
    content_service: ContentService,
    usage_service: UsageService,
    product_repository: ProductRepository,
    source_type: str = 'text',
) -> dict | None:
    feature = 'voice_post' if source_type == 'voice' else mode
    reservation = await usage_service.reserve(int(user['id']), feature)
    if not reservation:
        await _deny_access(message)
        return None
    await message.answer('Готовлю материал с учётом профиля канала…')
    try:
        result = await content_service.generate(
            user_id=int(user['id']),
            mode=mode,
            user_request=request,
            source_type=source_type,
        )
        channel = await product_repository.get_active_channel(int(user['id']))
        draft = await product_repository.create_draft(
            user_id=int(user['id']),
            channel_id=int(channel['id']) if channel else None,
            source_type=source_type,
            source_text=request,
            content_text=result,
            ai_mode=mode,
        )
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"<b>Не удалось подготовить материал.</b>\n\n{escape_html(str(exc))}")
        return None
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'generation_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'mode': mode, 'draft_id': int(draft['id']), 'access_source': reservation.source},
    )
    return draft


@router.callback_query(F.data.in_({'create:post', 'create:ideas', 'create:rewrite', 'create:cta'}))
async def create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    mode = callback.data.split(':')[1]
    _, prompt = MODE_INFO[mode]
    await state.clear()
    await state.update_data(mode=mode)
    await state.set_state(CreateStates.request)
    await callback.message.answer(f'<b>{prompt}</b>')
    await callback.answer()


@router.message(CreateStates.request, F.text)
async def create_from_text(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
    usage_service: UsageService,
    product_repository: ProductRepository,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    mode = str(data.get('mode') or 'post')
    user = await _get_user(message.from_user.id, queries)
    if not user:
        return
    draft = await _generate_draft(
        message, user, mode, message.text.strip(), content_service, usage_service, product_repository
    )
    await state.clear()
    if draft:
        await _send_model_text(message, str(draft['content_text']), draft_actions_keyboard(int(draft['id'])))


@router.callback_query(F.data == 'create:voice')
async def voice_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.set_state(CreateStates.voice)
    await callback.message.answer('<b>Пришлите голосовое или аудиофайл.</b>\n\nЯ превращу его в готовый пост.')
    await callback.answer()


@router.message(CreateStates.voice, F.voice | F.audio)
async def voice_received(
    message: Message,
    state: FSMContext,
    bot: Bot,
    queries: QueryService,
    transcription_service: TranscriptionService,
    content_service: ContentService,
    usage_service: UsageService,
    product_repository: ProductRepository,
) -> None:
    if not message.from_user:
        return
    user = await _get_user(message.from_user.id, queries)
    if not user:
        return
    reservation = await usage_service.reserve(int(user['id']), 'voice_post')
    if not reservation:
        await state.clear()
        await _deny_access(message)
        return
    media = message.voice or message.audio
    suffix = '.ogg' if message.voice else Path(getattr(message.audio, 'file_name', '') or 'audio.mp3').suffix
    with tempfile.NamedTemporaryFile(suffix=suffix or '.mp3', delete=False) as temp:
        path = Path(temp.name)
    try:
        await message.answer('Расшифровываю голосовое и собираю пост…')
        await bot.download(media, destination=path)
        transcript = await transcription_service.transcribe(path)
        result = await content_service.generate(
            user_id=int(user['id']), mode='post', user_request=transcript, source_type='voice'
        )
        channel = await product_repository.get_active_channel(int(user['id']))
        draft = await product_repository.create_draft(
            user_id=int(user['id']),
            channel_id=int(channel['id']) if channel else None,
            source_type='voice',
            source_text=transcript,
            content_text=result,
            ai_mode='post',
        )
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"<b>Не удалось обработать голосовое.</b>\n\n{escape_html(str(exc))}")
        return
    finally:
        path.unlink(missing_ok=True)
        await state.clear()
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'generation_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        payload={'mode': 'voice_post', 'draft_id': int(draft['id']), 'access_source': reservation.source},
    )
    await _send_model_text(message, str(draft['content_text']), draft_actions_keyboard(int(draft['id'])))


@router.callback_query(F.data == 'draft:list')
async def list_drafts(callback: CallbackQuery, queries: QueryService, product_repository: ProductRepository) -> None:
    if not callback.message:
        return
    user = await _get_user(callback.from_user.id, queries)
    drafts = await product_repository.list_drafts(int(user['id'])) if user else []
    if not drafts:
        await callback.message.answer('Черновиков пока нет.')
    else:
        await callback.message.answer('<b>Мои черновики</b>', reply_markup=drafts_keyboard(drafts))
    await callback.answer()


@router.callback_query(F.data.startswith('draft:view:'))
async def view_draft(callback: CallbackQuery, queries: QueryService, product_repository: ProductRepository) -> None:
    if not callback.message:
        return
    user = await _get_user(callback.from_user.id, queries)
    draft_id = int(callback.data.rsplit(':', 1)[1])
    draft = await product_repository.get_draft(draft_id, int(user['id'])) if user else None
    if not draft:
        await callback.answer('Черновик не найден', show_alert=True)
        return
    await _send_model_text(callback.message, str(draft['content_text']), draft_actions_keyboard(draft_id))
    await callback.answer()


@router.callback_query(F.data.startswith('draft:redo:'))
async def redo_draft(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not callback.message:
        return
    user = await _get_user(callback.from_user.id, queries)
    draft_id = int(callback.data.rsplit(':', 1)[1])
    draft = await product_repository.get_draft(draft_id, int(user['id'])) if user else None
    if not draft:
        await callback.answer('Черновик не найден', show_alert=True)
        return
    mode = str(draft.get('ai_mode') or 'post')
    reservation = await usage_service.reserve(int(user['id']), mode)
    if not reservation:
        await _deny_access(callback)
        return
    await callback.answer('Переделываю')
    try:
        result = await content_service.generate(
            int(user['id']), mode, str(draft.get('source_text') or draft['content_text']), source_type='regenerate'
        )
        updated = await product_repository.update_draft_text(draft_id, int(user['id']), result, 'regenerated')
    except Exception as exc:
        await usage_service.refund(reservation)
        await callback.message.answer(f"Не удалось переделать: {escape_html(str(exc))}")
        return
    await usage_service.commit(reservation)
    await _send_model_text(callback.message, str(updated['content_text']), draft_actions_keyboard(draft_id))


@router.callback_query(F.data.startswith('draft:improve:'))
async def improve_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    draft_id = int(callback.data.rsplit(':', 1)[1])
    await state.clear()
    await state.update_data(draft_id=draft_id)
    await state.set_state(CreateStates.improve_instruction)
    await callback.message.answer('Что изменить? Например: «сделай начало сильнее и сократи на треть».')
    await callback.answer()


@router.message(CreateStates.improve_instruction, F.text)
async def improve_draft(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await _get_user(message.from_user.id, queries)
    draft_id = int(data['draft_id'])
    draft = await product_repository.get_draft(draft_id, int(user['id'])) if user else None
    if not draft:
        await state.clear()
        await message.answer('Черновик не найден.')
        return
    reservation = await usage_service.reserve(int(user['id']), 'improve')
    if not reservation:
        await state.clear()
        await _deny_access(message)
        return
    try:
        result = await content_service.improve_draft(
            int(user['id']), str(draft['content_text']), message.text.strip()
        )
        updated = await product_repository.update_draft_text(draft_id, int(user['id']), result, 'improved')
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"Не удалось улучшить текст: {escape_html(str(exc))}")
        return
    finally:
        await state.clear()
    await usage_service.commit(reservation)
    await _send_model_text(message, str(updated['content_text']), draft_actions_keyboard(draft_id))


@router.callback_query(F.data.startswith('draft:edit:'))
async def edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.update_data(draft_id=int(callback.data.rsplit(':', 1)[1]))
    await state.set_state(CreateStates.manual_edit)
    await callback.message.answer('Пришлите новую полную версию текста. Это не спишет AI-действие.')
    await callback.answer()


@router.message(CreateStates.manual_edit, F.text)
async def edit_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await _get_user(message.from_user.id, queries)
    draft_id = int(data['draft_id'])
    updated = await product_repository.update_draft_text(
        draft_id, int(user['id']), message.text.strip(), 'manual_edit'
    ) if user else None
    await state.clear()
    if not updated:
        await message.answer('Черновик не найден.')
        return
    await _send_model_text(message, str(updated['content_text']), draft_actions_keyboard(draft_id))


@router.callback_query(F.data.startswith('draft:publish:'))
async def publish_now(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    publishing_service: PublishingService,
    settings: Settings,
) -> None:
    if not callback.message:
        return
    if not settings.feature_publishing:
        await callback.answer('Публикация временно выключена', show_alert=True)
        return
    user = await _get_user(callback.from_user.id, queries)
    try:
        await publishing_service.publish_now(bot, int(user['id']), int(callback.data.rsplit(':', 1)[1]))
    except Exception as exc:
        await callback.message.answer(f"<b>Не удалось опубликовать.</b>\n\n{escape_html(str(exc))}")
        await callback.answer('Ошибка публикации', show_alert=True)
        return
    await callback.message.answer('<b>Пост опубликован.</b>')
    await publishing_service.repository.log_activity(
        'publication_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'draft_id': int(callback.data.rsplit(':', 1)[1])},
    )
    await callback.answer('Готово')


@router.callback_query(F.data.startswith('draft:schedule:'))
async def schedule_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.update_data(draft_id=int(callback.data.rsplit(':', 1)[1]))
    await state.set_state(CreateStates.schedule_time)
    await callback.message.answer(
        '<b>Когда опубликовать?</b>\n\nПришлите дату и время в формате <code>25.08.2026 18:30</code>. '
        'Используется часовой пояс подключённого канала.'
    )
    await callback.answer()


@router.message(CreateStates.schedule_time, F.text)
async def schedule_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await _get_user(message.from_user.id, queries)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not channel:
        await state.clear()
        await message.answer('Сначала подключите канал.')
        return
    try:
        local_dt = datetime.strptime(message.text.strip(), '%d.%m.%Y %H:%M')
        local_dt = local_dt.replace(tzinfo=ZoneInfo(str(channel['timezone'])))
        publish_at = local_dt.astimezone(timezone.utc)
        if publish_at <= datetime.now(timezone.utc):
            raise ValueError
    except (ValueError, ZoneInfoNotFoundError):
        await message.answer('Не получилось прочитать время. Пример: <code>25.08.2026 18:30</code>.')
        return
    schedule = await product_repository.create_schedule(
        draft_id=int(data['draft_id']),
        user_id=int(user['id']),
        channel_id=int(channel['id']),
        publish_at=publish_at.isoformat(),
    )
    await state.clear()
    await message.answer(
        f"<b>Публикация запланирована.</b>\n\n{local_dt.strftime('%d.%m.%Y в %H:%M')} "
        f"({escape_html(str(channel['timezone']))}), задача #{schedule['id']}."
    )
    await product_repository.log_activity(
        'publication_scheduled',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'draft_id': int(data['draft_id']), 'schedule_id': int(schedule['id'])},
    )


@router.callback_query(F.data.startswith('draft:image:'))
async def image_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.update_data(draft_id=int(callback.data.rsplit(':', 1)[1]))
    await state.set_state(CreateStates.image_prompt)
    await callback.message.answer('Опишите желаемое изображение или напишите «по смыслу поста».')
    await callback.answer()


@router.message(CreateStates.image_prompt, F.text)
async def image_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    usage_service: UsageService,
    image_service: ImageService,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await _get_user(message.from_user.id, queries)
    draft_id = int(data['draft_id'])
    draft = await product_repository.get_draft(draft_id, int(user['id'])) if user else None
    if not draft:
        await state.clear()
        await message.answer('Черновик не найден.')
        return
    reservation = await usage_service.reserve(int(user['id']), 'image')
    if not reservation:
        await state.clear()
        await _deny_access(message)
        return
    request = message.text.strip()
    prompt = (
        'Создай выразительное изображение для Telegram-поста без текста и логотипов. '
        f"Пожелание: {request}. Смысл поста: {str(draft['content_text'])[:1800]}"
    )
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp:
        path = Path(temp.name)
    try:
        await message.answer('Генерирую изображение…')
        await image_service.generate_image(prompt, path)
        sent = await message.answer_photo(FSInputFile(path), caption='Изображение добавлено к черновику.')
        file_id = sent.photo[-1].file_id
        await product_repository.set_draft_image(draft_id, int(user['id']), file_id, prompt)
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"Не удалось создать изображение: {escape_html(str(exc))}")
        return
    finally:
        path.unlink(missing_ok=True)
        await state.clear()
    await usage_service.commit(reservation)
    await message.answer('Черновик обновлён.', reply_markup=draft_actions_keyboard(draft_id))
