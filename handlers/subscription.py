from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from config import Settings
from database.queries import QueryService
from handlers.analysis_delivery import deliver_pending_free_analysis
from keyboards.inline import subscription_keyboard
from keyboards.reply import main_menu_keyboard
from states.generation_states import GenerationStates
from states.onboarding_states import OnboardingStates
from utils.texts import MENU_TEXT, ONBOARDING_INTRO_TEXT, SUBSCRIPTION_REQUIRED_TEXT, SUBSCRIPTION_SUCCESS_TEXT

router = Router()


async def _is_member(bot: Bot, user_id: int, channel_id: str) -> bool:
    member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    return member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


@router.callback_query(lambda c: c.data == 'check_subscription')
async def check_subscription(callback: CallbackQuery, state: FSMContext, bot: Bot, queries: QueryService, settings: Settings) -> None:
    if not callback.from_user or not callback.message:
        return
    try:
        subscribed = await _is_member(bot, callback.from_user.id, settings.channel_id)
    except Exception:
        await callback.answer('Не удалось проверить подписку. Убедитесь, что бот админ канала.', show_alert=True)
        return

    if not subscribed:
        await queries.set_user_subscription(callback.from_user.id, False)
        await callback.message.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=subscription_keyboard(settings.channel_link))
        await callback.answer('Подписка пока не найдена')
        return

    await queries.set_user_subscription(callback.from_user.id, True)
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if user and await deliver_pending_free_analysis(
        callback.message,
        state,
        queries,
        int(user['id']),
    ):
        await callback.answer('Подписка подтверждена — разбор выдан')
        return

    current_state = await state.get_state()
    if current_state == GenerationStates.waiting_for_analysis_subscription.state:
        await callback.message.answer(
            '<b>Подписка подтверждена.</b>\n\nРазбор ещё готовится. Как только он будет готов, я пришлю его автоматически.'
        )
        await callback.answer('Подписка подтверждена')
        return
    if current_state == GenerationStates.waiting_for_options.state:
        await callback.answer('Подписка подтверждена')
        return

    await callback.message.answer(SUBSCRIPTION_SUCCESS_TEXT)
    if user and not user.get('is_onboarding_completed'):
        await callback.message.answer(ONBOARDING_INTRO_TEXT)
        await state.set_state(OnboardingStates.waiting_for_name)
    else:
        await callback.message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=callback.from_user.id in settings.admin_ids))
    await callback.answer('Готово')
