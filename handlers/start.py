from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from keyboards.inline import subscription_keyboard
from keyboards.reply import main_menu_keyboard
from states.onboarding_states import OnboardingStates
from utils.texts import MENU_TEXT, ONBOARDING_INTRO_TEXT, SUBSCRIPTION_REQUIRED_TEXT, WELCOME_TEXT

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, queries: QueryService, settings: Settings) -> None:
    if not message.from_user:
        return
    is_admin = message.from_user.id in settings.admin_ids
    await queries.create_or_update_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        full_name=message.from_user.full_name,
        is_admin=is_admin,
    )
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    await state.clear()
    await message.answer(WELCOME_TEXT)

    if not user or not user.get('is_subscribed'):
        await message.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(settings.channel_link))
        return

    if not user.get('is_onboarding_completed'):
        await message.answer(ONBOARDING_INTRO_TEXT)
        await state.set_state(OnboardingStates.waiting_for_name)
        return

    await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=is_admin))
