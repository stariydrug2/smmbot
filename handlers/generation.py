from __future__ import annotations

import uuid
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Document, Message

from database.queries import QueryService
from keyboards.inline import (
    content_plan_keyboard,
    photo_options_keyboard,
    post_actions_keyboard,
    visual_text_options_keyboard,
    voice_after_transcription_keyboard,
)
from services.content_service import ContentService
from services.image_service import ImageService
from services.openai_service import OpenAIService
from services.transcription_service import TranscriptionService
from states.generation_states import GenerationStates
from utils.helpers import ensure_dir, escape_html, render_model_text

router = Router()

MODE_MAP = {
    '💡 Идея поста': 'post',
    '📝 Готовый пост': 'post',
    '🧵 Серия постов': 'series',
    '♻️ Рерайт': 'rewrite',
    '📌 CTA': 'cta',
    '📣 Story-анонс': 'story',
}


@router.message(GenerationStates.choosing_mode, F.text.in_(MODE_MAP.keys()))
async def choose_generation_mode(message: Message, state: FSMContext) -> None:
    mode = MODE_MAP[message.text]
    await state.update_data(mode=mode, mode_label=message.text)
    if mode == 'rewrite':
        await state.set_state(GenerationStates.waiting_for_rewrite_text)
        await message.answer('<b>Пришлите текст для рерайта.</b>')
        return
    await state.set_state(GenerationStates.waiting_for_topic)
    await message.answer('<b>Пришлите текст, тему или тезисы.</b>')


@router.message(GenerationStates.waiting_for_topic)
async def generation_topic(message: Message, state: FSMContext) -> None:
    await state.update_data(topic=message.text or '')
    await state.set_state(GenerationStates.waiting_for_goal)
    await message.answer('<b>Какая цель у материала?</b> Например: вовлечение, продажа, прогрев, объяснение.')


@router.message(GenerationStates.waiting_for_goal)
async def generation_goal(message: Message, state: FSMContext) -> None:
    await state.update_data(goal=message.text or '')
    await state.set_state(GenerationStates.waiting_for_style)
    await message.answer('<b>Какой нужен стиль?</b> Например: деловой, живой, экспертный, мягкий.')


@router.message(GenerationStates.waiting_for_style)
async def generation_style(message: Message, state: FSMContext) -> None:
    await state.update_data(style=message.text or '')
    await state.set_state(GenerationStates.waiting_for_length)
    await message.answer('<b>Какая длина нужна?</b> Коротко, средне, подробно.')


@router.message(GenerationStates.waiting_for_length)
async def generation_length(message: Message, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    data = await state.get_data()
    mode = data.get('mode', 'post')
    try:
        result = await content_service.generate(
            user_id=user['id'],
            mode=mode,
            user_request=str(data.get('topic', '')),
            source_type='text',
            goal=data.get('goal'),
            tone=data.get('style'),
            length=message.text,
        )
    except RuntimeError as exc:
        await message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        return
    await state.update_data(last_result=result, original_request=data.get('topic', ''), length=message.text or '')
    await message.answer(f"<b>Готово.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
    await state.set_state(GenerationStates.waiting_for_options)


@router.message(GenerationStates.waiting_for_rewrite_text)
async def generation_rewrite(message: Message, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    try:
        result = await content_service.generate(user_id=user['id'], mode='rewrite', user_request=message.text or '', source_type='text')
    except RuntimeError as exc:
        await message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        return
    await state.update_data(last_result=result, original_request=message.text or '', mode='rewrite')
    await message.answer(f"<b>Результат рерайта.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
    await state.set_state(GenerationStates.waiting_for_options)


@router.message(GenerationStates.waiting_for_content_plan_brief)
async def generation_content_plan(message: Message, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    try:
        result = await content_service.generate(user_id=user['id'], mode='content_plan', user_request=message.text or '', source_type='text')
    except RuntimeError as exc:
        await message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        return
    await state.update_data(last_result=result, original_request=message.text or '', mode='content_plan')
    await message.answer(f"<b>Контент-план на 7 дней.</b>\n\n{render_model_text(result)}", reply_markup=content_plan_keyboard())
    await state.set_state(GenerationStates.waiting_for_options)


@router.callback_query(lambda c: c.data and c.data.startswith('content:'))
async def content_transform(callback: CallbackQuery, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    data = await state.get_data()
    original = str(data.get('last_result') or data.get('original_request') or '')
    action = callback.data.split(':', maxsplit=1)[1]
    if action == 'save':
        await callback.answer('Материал уже сохранён в истории.')
        return
    tasks = {
        'redo': 'Пересобери материал, сохранив смысл, но поменяй структуру и подачу.',
        'shorter': 'Сделай текст короче и плотнее.',
        'stronger': 'Сделай текст сильнее и убедительнее.',
        'expert': 'Сделай текст экспертнее, но без перегруза.',
        'softer': 'Сделай текст мягче и деликатнее.',
        'cta': 'Добавь уместный CTA в конце.',
        'visual': 'Предложи идею визуала к этому материалу.',
    }
    mode = 'visual' if action == 'visual' else 'post'
    try:
        result = await content_service.generate(user_id=user['id'], mode=mode, user_request=f'{original}\n\nДоп. задача: {tasks[action]}', source_type='text')
    except RuntimeError as exc:
        await callback.message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        await callback.answer()
        return
    await state.update_data(last_result=result)
    await callback.message.answer(f"<b>Обновлённый вариант.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
    await callback.answer()


@router.message(GenerationStates.waiting_for_voice, F.voice | F.audio)
async def handle_voice(message: Message, state: FSMContext, queries: QueryService, transcription_service: TranscriptionService) -> None:
    if not message.from_user:
        return
    media = message.voice or message.audio
    if not media:
        await message.answer('Нужно отправить голосовое или аудио.')
        return
    tg_file = await message.bot.get_file(media.file_id)
    local_dir = ensure_dir(Path('tmp/audio'))
    local_path = local_dir / f'{uuid.uuid4()}.ogg'
    await message.bot.download_file(tg_file.file_path, destination=local_path)
    try:
        transcript = await transcription_service.transcribe(local_path)
    except RuntimeError as exc:
        await message.answer(f"<b>Ошибка распознавания.</b>\n\n{escape_html(str(exc))}")
        local_path.unlink(missing_ok=True)
        return
    finally:
        local_path.unlink(missing_ok=True)
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.add_generation_history(user['id'], 'voice_transcript', 'voice', '[voice]', transcript, None)
    await state.update_data(voice_transcript=transcript)
    await message.answer(f"<b>Распознанный текст:</b>\n\n{render_model_text(transcript)}", reply_markup=voice_after_transcription_keyboard())
    await state.set_state(GenerationStates.waiting_for_options)


@router.callback_query(lambda c: c.data and c.data.startswith('voice:'))
async def handle_voice_action(callback: CallbackQuery, state: FSMContext, queries: QueryService, content_service: ContentService) -> None:
    if not callback.from_user or not callback.message:
        return
    transcript = str((await state.get_data()).get('voice_transcript') or '')
    if not transcript:
        await callback.answer('Сначала отправьте голосовое.', show_alert=True)
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    action = callback.data.split(':', maxsplit=1)[1]
    if action == 'save':
        await callback.answer('Материал сохранён в истории.')
        return
    mode_map = {'post': 'post', 'series': 'series', 'plan': 'content_plan', 'story': 'story'}
    try:
        result = await content_service.generate(user_id=user['id'], mode=mode_map[action], user_request=transcript, source_type='voice')
    except RuntimeError as exc:
        await callback.message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        await callback.answer()
        return
    await state.update_data(last_result=result, original_request=transcript)
    await callback.message.answer(f"<b>Готово.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
    await callback.answer()


@router.message(GenerationStates.waiting_for_photo, F.photo)
async def handle_photo(message: Message, state: FSMContext) -> None:
    await state.update_data(photo_file_id=message.photo[-1].file_id, visual_text_request='')
    await state.set_state(GenerationStates.waiting_for_options)
    await message.answer('<b>Что сделать с этим фото?</b>', reply_markup=photo_options_keyboard())


@router.message(GenerationStates.waiting_for_photo, F.text)
async def handle_visual_text(message: Message, state: FSMContext) -> None:
    prompt = (message.text or '').strip()
    if not prompt:
        await message.answer('<b>Нужно прислать текстовое описание изображения.</b>')
        return
    await state.update_data(visual_text_request=prompt, photo_file_id='')
    await state.set_state(GenerationStates.waiting_for_visual_request)
    await message.answer(
        '<b>Понял задачу.</b>\n\nВыберите, что сделать дальше: сгенерировать картинку сразу или сначала предложить идею визуала.',
        reply_markup=visual_text_options_keyboard(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith('visual_text:'))
async def handle_visual_text_action(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    content_service: ContentService,
    image_service: ImageService,
) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    data = await state.get_data()
    visual_request = str(data.get('visual_text_request') or '').strip()
    if not visual_request:
        await callback.answer('Сначала отправьте текстовое описание.', show_alert=True)
        return

    action = callback.data.split(':', maxsplit=1)[1]

    if action == 'idea':
        try:
            result = await content_service.generate(user_id=user['id'], mode='visual', user_request=visual_request, source_type='text')
        except RuntimeError as exc:
            await callback.message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
            await callback.answer()
            return
        await state.update_data(last_result=result, original_request=visual_request)
        await callback.message.answer(f"<b>Идея визуала.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
        await callback.answer()
        return

    await callback.answer('Запускаю генерацию изображения...')
    await callback.message.answer('<b>Генерирую изображение по описанию.</b>\n\nЭто может занять немного времени.')
    try:
        prompt_result = await content_service.generate(
            user_id=user['id'],
            mode='image_prompt',
            user_request=visual_request,
            source_type='text',
        )
        final_prompt = _extract_final_image_prompt(prompt_result)
        out_dir = ensure_dir(Path('tmp/images'))
        out_path = out_dir / f'{uuid.uuid4()}.png'
        try:
            image_path = await image_service.generate_image(final_prompt, out_path)
            await callback.message.answer_photo(
                photo=image_path.read_bytes(),
                caption=f"<b>Изображение готово.</b>\n\n<b>Промпт:</b> {escape_html(final_prompt[:800])}",
            )
        finally:
            out_path.unlink(missing_ok=True)
        await queries.add_generation_history(user['id'], 'image_generation', 'text', visual_request, final_prompt, {'mode': 'text_to_image'})
        await state.update_data(last_result=prompt_result, original_request=visual_request)
    except RuntimeError as exc:
        await callback.message.answer(f'<b>Ошибка генерации изображения.</b>\n\n{escape_html(str(exc))}')
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('photo:'))
async def handle_photo_action(callback: CallbackQuery, state: FSMContext, queries: QueryService, content_service: ContentService, image_service: ImageService, openai_service: OpenAIService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    if not (await state.get_data()).get('photo_file_id'):
        await callback.answer('Сначала отправьте фото.', show_alert=True)
        return
    action = callback.data.split(':', maxsplit=1)[1]
    photo_file_id = (await state.get_data())['photo_file_id']
    tg_file = await callback.message.bot.get_file(photo_file_id)
    local_dir = ensure_dir(Path('tmp/photos'))
    local_path = local_dir / f'{uuid.uuid4()}.jpg'
    await callback.message.bot.download_file(tg_file.file_path, destination=local_path)

    if action == 'generate':
        await callback.answer('Запускаю генерацию...')
        await callback.message.answer('<b>Генерирую новое изображение на основе фото.</b>\n\nЭто может занять немного времени.')
        try:
            prompt_result = await openai_service.generate_with_image(
                local_path,
                'Подготовь точный промпт для генерации нового изображения на основе присланного фото и контекста бренда. Верни только короткую концепцию и одну финальную строку промпта без markdown-разметки.',
                system_prompt='Ты Telegram-SMM редактор и арт-директор.',
            )
            final_prompt = _extract_final_image_prompt(prompt_result)
            out_dir = ensure_dir(Path('tmp/images'))
            out_path = out_dir / f'{uuid.uuid4()}.png'
            try:
                image_path = await image_service.generate_image(final_prompt, out_path)
                await callback.message.answer_photo(
                    photo=image_path.read_bytes(),
                    caption=f"<b>Изображение готово.</b>\n\n<b>Промпт:</b> {escape_html(final_prompt[:800])}",
                )
            finally:
                out_path.unlink(missing_ok=True)
        except RuntimeError as exc:
            await callback.message.answer(f'<b>Ошибка генерации изображения.</b>\n\n{escape_html(str(exc))}')
        finally:
            local_path.unlink(missing_ok=True)
        return

    prompts = {
        'post': 'Придумай Telegram-пост по фото, учитывая композицию, настроение и контекст бренда.',
        'caption': 'Придумай короткую и сильную подпись к фото для Telegram.',
        'visual_series': 'Предложи идею визуальной серии на основе этого фото: 3 варианта развития визуала для контента.',
        'mood': 'Проанализируй настроение, подачу, атмосферу и маркетинговый потенциал фото для контента бренда.',
    }
    try:
        result = await openai_service.generate_with_image(local_path, prompts[action], system_prompt='Ты профессиональный AI-контент-оператор для Telegram.')
    except RuntimeError as exc:
        await callback.message.answer(f'<b>Ошибка обработки фото.</b>\n\n{escape_html(str(exc))}')
        local_path.unlink(missing_ok=True)
        await callback.answer()
        return
    finally:
        local_path.unlink(missing_ok=True)
    await queries.add_generation_history(user['id'], f'photo_{action}', 'photo', '[photo]', result, None)
    await callback.message.answer(f"<b>Готово.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())
    await callback.answer()


@router.message(GenerationStates.waiting_for_photo, F.document)
async def handle_document(message: Message, queries: QueryService, content_service: ContentService) -> None:
    if not message.from_user or not message.document:
        return
    document: Document = message.document
    if not (document.mime_type or '').startswith('text/'):
        await message.answer('Пока поддерживаются только текстовые документы.')
        return
    tg_file = await message.bot.get_file(document.file_id)
    local_dir = ensure_dir(Path('tmp/docs'))
    local_path = local_dir / f"{uuid.uuid4()}_{document.file_name or 'input.txt'}"
    await message.bot.download_file(tg_file.file_path, destination=local_path)
    text = local_path.read_text(encoding='utf-8', errors='ignore')
    local_path.unlink(missing_ok=True)
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    try:
        result = await content_service.generate(user_id=user['id'], mode='post', user_request=text, source_type='document')
    except RuntimeError as exc:
        await message.answer(f'<b>Ошибка генерации.</b>\n\n{escape_html(str(exc))}')
        return
    await message.answer(f"<b>Пост по документу готов.</b>\n\n{render_model_text(result)}", reply_markup=post_actions_keyboard())


def _extract_final_image_prompt(raw_text: str) -> str:
    cleaned = raw_text.replace('\r\n', '\n').strip()
    lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
    if not lines:
        return cleaned

    markers = ('итоговый промпт:', 'prompt:', 'final prompt:', 'промпт:')
    for line in reversed(lines):
        lowered = line.lower()
        for marker in markers:
            if lowered.startswith(marker):
                return line.split(':', maxsplit=1)[1].strip()

    return lines[-1]
