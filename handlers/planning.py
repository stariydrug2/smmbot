from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database.product_repository import ProductRepository
from database.queries import QueryService
from handlers.content import _deny_access, _send_model_text
from keyboards.product import draft_actions_keyboard, schedules_keyboard
from services.content_service import ContentService
from services.usage_service import UsageService
from states.product_states import PlanStates
from utils.helpers import escape_html

router = Router()


def _schedule_time(value: str, timezone_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo(timezone_name)).strftime('%d.%m.%Y %H:%M')
    except (ValueError, KeyError):
        return value


@router.callback_query(F.data == 'plan:generate')
async def plan_generate_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.clear()
    await state.set_state(PlanStates.brief)
    await callback.message.answer(
        '<b>План на 7 дней</b>\n\nОпишите задачу недели: что продвигаем, какие события учитывать '
        'и какого результата ждём.'
    )
    await callback.answer()


@router.message(PlanStates.brief, F.text)
async def plan_brief_received(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    content_service: ContentService,
    usage_service: UsageService,
) -> None:
    if not message.from_user:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    reservation = await usage_service.reserve(int(user['id']), 'content_plan')
    if not reservation:
        await state.clear()
        await _deny_access(message)
        return
    await message.answer('Собираю темы в связный план…')
    try:
        result = await content_service.generate(
            int(user['id']), 'content_plan', message.text.strip(), source_type='plan'
        )
        channel = await product_repository.get_active_channel(int(user['id']))
        draft = await product_repository.create_draft(
            user_id=int(user['id']),
            channel_id=int(channel['id']) if channel else None,
            source_type='plan',
            source_text=message.text.strip(),
            content_text=result,
            ai_mode='content_plan',
        )
    except Exception as exc:
        await usage_service.refund(reservation)
        await message.answer(f"<b>Не удалось собрать план.</b>\n\n{escape_html(str(exc))}")
        return
    finally:
        await state.clear()
    await usage_service.commit(reservation)
    await product_repository.log_activity(
        'generation_completed',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'mode': 'content_plan', 'draft_id': int(draft['id']), 'access_source': reservation.source},
    )
    await _send_model_text(message, str(draft['content_text']), draft_actions_keyboard(int(draft['id'])))


@router.callback_query(F.data == 'plan:list')
async def plan_list(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    schedules = await product_repository.list_schedules(int(user['id'])) if user else []
    if not schedules:
        await callback.message.answer('Запланированных публикаций пока нет.')
        await callback.answer()
        return
    lines = ['<b>Запланированные публикации</b>', '']
    for item in schedules:
        preview = escape_html(str(item.get('content_text') or '').replace('\n', ' ')[:80])
        status = {
            'scheduled': 'запланировано',
            'processing': 'публикуется',
            'failed': 'ожидает повтора',
            'interrupted': 'нужно проверить канал',
        }.get(str(item['status']), str(item['status']))
        lines.append(
            f"<b>#{item['id']}</b> · {escape_html(_schedule_time(str(item['publish_at']), str(item['timezone'])))} · "
            f"{escape_html(status)}\n{preview}"
        )
    await callback.message.answer('\n\n'.join(lines), reply_markup=schedules_keyboard(schedules))
    await callback.answer()


@router.callback_query(F.data.startswith('schedule:cancel:'))
async def schedule_cancel(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    schedule_id = int(callback.data.rsplit(':', 1)[1])
    cancelled = await product_repository.cancel_schedule(schedule_id, int(user['id'])) if user else False
    await callback.answer('Публикация отменена' if cancelled else 'Не удалось отменить', show_alert=not cancelled)
    if cancelled and callback.message:
        await callback.message.answer(f'Задача #{schedule_id} отменена. Черновик сохранён.')
