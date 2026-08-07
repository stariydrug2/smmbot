from __future__ import annotations

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.queries import QueryService
from keyboards.inline import after_analysis_keyboard
from states.generation_states import GenerationStates
from utils.helpers import render_model_text


_delivery_locks: dict[int, asyncio.Lock] = {}


async def deliver_pending_free_analysis(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    user_id: int,
) -> bool:
    lock = _delivery_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        analysis = await queries.get_pending_free_analysis(user_id)
        if not analysis:
            return False

        await message.answer(
            f"<b>Разбор готов.</b>\n\n{render_model_text(str(analysis['result_text']))}"
        )
        await queries.mark_analysis_delivered(int(analysis['id']), user_id)

        posts_count = max(1, int(analysis.get('posts_count') or 1))
        await state.update_data(
            last_analyzed_post=str(analysis.get('original_text') or '') if posts_count == 1 else '',
            last_analysis_posts_count=posts_count,
        )
        await state.set_state(GenerationStates.waiting_for_options)
        await message.answer(
            '<b>Я могу не только показать слабые места, но и полностью усилить этот пост:</b>\n'
            '• переписать начало\n'
            '• убрать воду\n'
            '• выстроить структуру\n'
            '• добавить сильный CTA\n'
            '• сделать текст живее\n\n'
            'Для этого подойдет тариф “Старт”.',
            reply_markup=after_analysis_keyboard(),
        )
        return True
