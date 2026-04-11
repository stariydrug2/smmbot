from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from database.queries import QueryService
from keyboards.inline import history_keyboard
from utils.formatting import format_history
from utils.helpers import escape_html

router = Router()


@router.message(F.text == '🕘 История')
async def history_entry(message: Message, queries: QueryService) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    records = await queries.get_generation_history(user['id'], limit=15)
    await message.answer(format_history(records), reply_markup=history_keyboard(records))


@router.callback_query(lambda c: c.data and c.data.startswith('history:view:'))
async def history_view(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    record_id = int(callback.data.split(':')[-1])
    record = await queries.get_generation_record(record_id, user['id'])
    if not record:
        await callback.answer('Запись не найдена', show_alert=True)
        return
    text = (
        f"<b>Запись #{record['id']}</b>\n\n"
        f"<b>Тип:</b> {escape_html(record['generation_type'])}\n"
        f"<b>Источник:</b> {escape_html(record['source_type'])}\n"
        f"<b>Дата:</b> {escape_html(record['created_at'])}\n\n"
        f"<b>Вход:</b>\n{escape_html(record['input_text'])}\n\n"
        f"<b>Результат:</b>\n{escape_html(record['output_text'])}"
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('history:delete:'))
async def history_delete(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return
    record_id = int(callback.data.split(':')[-1])
    await queries.delete_generation_record(record_id, user['id'])
    records = await queries.get_generation_history(user['id'], limit=15)
    await callback.message.answer('<b>Запись удалена.</b>', reply_markup=history_keyboard(records))
    await callback.answer()
