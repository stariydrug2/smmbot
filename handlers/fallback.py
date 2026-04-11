from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from utils.texts import OFFTOP_TEXT

router = Router()


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    await message.answer(OFFTOP_TEXT)
