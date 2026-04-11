from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from keyboards.reply import main_menu_keyboard, onboarding_lengths_keyboard
from states.onboarding_states import OnboardingStates
from utils.validators import is_meaningful_text

router = Router()


@router.message(OnboardingStates.waiting_for_name)
async def onboarding_name(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Введите имя в текстовом виде.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], person_name=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_brand_name)
    await message.answer('<b>Как называется бренд или проект?</b>')


@router.message(OnboardingStates.waiting_for_brand_name)
async def onboarding_brand_name(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Напишите название бренда или проекта.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], brand_name=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_brand_description)
    await message.answer('<b>Чем занимается бренд или проект?</b>')


@router.message(OnboardingStates.waiting_for_brand_description)
async def onboarding_brand_description(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text, min_length=5):
        await message.answer('Нужно коротко описать, чем занимается проект.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], brand_description=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_usage_goal)
    await message.answer('<b>Для чего планируете использовать бота?</b>')


@router.message(OnboardingStates.waiting_for_usage_goal)
async def onboarding_usage_goal(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Опишите задачу бота в свободной форме.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], usage_goal=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_target_audience)
    await message.answer('<b>Кто основная аудитория?</b>')


@router.message(OnboardingStates.waiting_for_target_audience)
async def onboarding_target_audience(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Напишите, для кого будут публикации.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], target_audience=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_tone)
    await message.answer('<b>Какой тон общения нужен в публикациях?</b>')


@router.message(OnboardingStates.waiting_for_tone)
async def onboarding_tone(message: Message, state: FSMContext, queries: QueryService) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Напишите желаемый tone of voice.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], tone_of_voice=message.text.strip())
    await state.set_state(OnboardingStates.waiting_for_post_length)
    await message.answer('<b>Какая длина постов предпочтительна?</b>', reply_markup=onboarding_lengths_keyboard())


@router.message(OnboardingStates.waiting_for_post_length)
async def onboarding_post_length(message: Message, state: FSMContext, queries: QueryService, settings: Settings) -> None:
    if not message.from_user or not is_meaningful_text(message.text):
        await message.answer('Выберите или напишите желаемую длину постов.')
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    await queries.update_brand_profile(user['id'], post_length=message.text.strip())
    await queries.set_onboarding_completed(message.from_user.id, True)
    await state.clear()
    await message.answer('<b>Профиль сохранён.</b>\n\nТеперь можно переходить к созданию контента.', reply_markup=main_menu_keyboard(is_admin=message.from_user.id in settings.admin_ids))
