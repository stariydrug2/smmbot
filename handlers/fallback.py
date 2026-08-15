from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from keyboards.reply import main_menu_keyboard
from utils.texts import OFFTOP_TEXT

router = Router()


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    await message.answer(OFFTOP_TEXT)


@router.callback_query()
async def fallback_callback(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer(
            'Эта кнопка относится к предыдущей версии бота. Откройте нужный раздел в новом меню.',
            reply_markup=main_menu_keyboard(callback.from_user.id in settings.admin_ids),
        )
    await callback.answer()
