from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from keyboards.inline import payment_plans_keyboard
from keyboards.reply import content_modes_keyboard, main_menu_keyboard
from services.subscription_service import SubscriptionService
from states.generation_states import GenerationStates
from utils.texts import HELP_TEXT, MENU_TEXT, PAYMENT_MENU_TEXT, PHOTO_WAIT_TEXT, VOICE_WAIT_TEXT

router = Router()


@router.message(F.text == 'ℹ️ Помощь')
async def show_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text == '✍️ Создать контент')
async def create_content_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(GenerationStates.choosing_mode)
    await message.answer('<b>Выберите режим генерации.</b>', reply_markup=content_modes_keyboard())


@router.message(F.text == '🗓 Контент-план')
async def content_plan_entry(message: Message, state: FSMContext) -> None:
    await state.update_data(mode='content_plan')
    await state.set_state(GenerationStates.waiting_for_content_plan_brief)
    await message.answer('<b>Опишите тему, цель и контекст для контент-плана на 7 дней.</b>')


@router.message(F.text == '🎙 Пост из голосового')
async def voice_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(GenerationStates.waiting_for_voice)
    await message.answer(VOICE_WAIT_TEXT)


@router.message(F.text == '🖼 Фото / визуал')
async def photo_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(GenerationStates.waiting_for_photo)
    await message.answer(PHOTO_WAIT_TEXT)


@router.message(F.text == '💳 Подписка')
async def payment_entry(message: Message, queries, subscription_service: SubscriptionService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    status = await subscription_service.get_status(int(user['id']))
    plans = await queries.get_subscription_plans()
    text = PAYMENT_MENU_TEXT
    if status.get('ends_at_human'):
        text += f"\n\n<b>Текущий статус:</b> {status['status']}\n<b>Действует до:</b> {status['ends_at_human']}"
    await message.answer(text, reply_markup=payment_plans_keyboard(plans))


@router.message(F.text == '⬅️ Назад')
async def back_to_menu(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=bool(message.from_user and message.from_user.id in settings.admin_ids)))


@router.callback_query(lambda c: c.data == 'go:menu')
async def callback_go_menu(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=bool(callback.from_user and callback.from_user.id in settings.admin_ids)))
    await callback.answer()
