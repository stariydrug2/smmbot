from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.queries import QueryService
from keyboards.inline import profile_keyboard
from services.memory_service import MemoryService
from services.subscription_service import SubscriptionService
from states.profile_states import ProfileStates
from utils.formatting import format_profile

router = Router()

FIELD_TO_STATE = {
    'person_name': ProfileStates.editing_person_name,
    'brand_name': ProfileStates.editing_brand_name,
    'brand_description': ProfileStates.editing_brand_description,
    'usage_goal': ProfileStates.editing_usage_goal,
    'target_audience': ProfileStates.editing_target_audience,
    'tone_of_voice': ProfileStates.editing_tone,
    'post_length': ProfileStates.editing_post_length,
    'preferred_formats': ProfileStates.editing_preferred_formats,
    'forbidden_words': ProfileStates.editing_forbidden_words,
}


@router.message(F.text == '👤 Личный кабинет')
async def profile_entry(message: Message, queries: QueryService, subscription_service: SubscriptionService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    profile = await queries.get_brand_profile(user['id'])
    summary = await queries.get_memory_summary(user['id'])
    history = await queries.get_generation_history(user['id'], limit=100)
    status = await subscription_service.get_status(user['id'])
    await message.answer(format_profile(profile, user, summary, len(history), status), reply_markup=profile_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith('profile:'))
async def profile_actions(callback: CallbackQuery, state: FSMContext, queries: QueryService, memory_service: MemoryService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    action = callback.data.split(':', maxsplit=1)[1]
    if action == 'refresh_memory':
        summary = await memory_service.refresh_summary(user['id'])
        await callback.message.answer(f"<b>Память бренда обновлена.</b>\n\n{summary}")
        await callback.answer()
        return
    if action == 'clear_history':
        await queries.clear_generation_history(user['id'])
        await callback.message.answer('<b>История генераций очищена.</b>')
        await callback.answer()
        return
    if action == 'examples':
        await state.set_state(ProfileStates.editing_examples)
        await callback.message.answer('<b>Отправьте один или несколько примеров постов.</b>\n\nСтарые примеры будут заменены новыми.')
        await callback.answer()
        return
    next_state = FIELD_TO_STATE.get(action)
    if next_state:
        await state.update_data(profile_field=action)
        await state.set_state(next_state)
        await callback.message.answer('<b>Введите новое значение.</b>')
    await callback.answer()


@router.message(ProfileStates.editing_examples)
async def edit_examples(message: Message, state: FSMContext, queries: QueryService, memory_service: MemoryService) -> None:
    if not message.from_user or not message.text:
        await message.answer('Нужно отправить текст примеров.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.clear_user_examples(user['id'])
    for chunk in [part.strip() for part in message.text.split('\n\n') if part.strip()]:
        await queries.add_user_example(user['id'], chunk)
    summary = await memory_service.refresh_summary(user['id'])
    await state.clear()
    await message.answer('<b>Примеры сохранены.</b>\n\nПамять бренда обновлена.')
    await message.answer(f"<b>Краткая память:</b>\n\n{summary}")


@router.message(ProfileStates.editing_person_name)
@router.message(ProfileStates.editing_brand_name)
@router.message(ProfileStates.editing_brand_description)
@router.message(ProfileStates.editing_usage_goal)
@router.message(ProfileStates.editing_target_audience)
@router.message(ProfileStates.editing_tone)
@router.message(ProfileStates.editing_post_length)
@router.message(ProfileStates.editing_preferred_formats)
@router.message(ProfileStates.editing_forbidden_words)
async def edit_profile_field(message: Message, state: FSMContext, queries: QueryService, memory_service: MemoryService) -> None:
    if not message.from_user or not message.text:
        await message.answer('Введите текстовое значение.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    field = (await state.get_data()).get('profile_field')
    if not field:
        await state.clear()
        return
    await queries.update_brand_profile(user['id'], **{field: message.text.strip()})
    await memory_service.refresh_summary(user['id'])
    await state.clear()
    await message.answer('<b>Поле обновлено.</b>')
