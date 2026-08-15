from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database.queries import QueryService
from keyboards.inline import free_analysis_keyboard
from keyboards.reply import main_menu_keyboard
from states.product_states import AnalysisStates
from services.publishing_service import PublishingService
from utils.helpers import render_model_text
from utils.texts import MENU_TEXT, WELCOME_TEXT

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    command: CommandObject,
    queries: QueryService,
    settings: Settings,
) -> None:
    if not message.from_user:
        return
    source, utm_source, utm_campaign = _parse_start_payload(command.args)
    is_admin = message.from_user.id in settings.admin_ids
    await queries.create_or_update_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        full_name=message.from_user.full_name,
        is_admin=is_admin,
        trial_days=settings.trial_days,
        source=source,
        utm_source=utm_source,
        utm_campaign=utm_campaign,
    )
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    pending = await queries.get_pending_free_analysis(int(user['id'])) if user else None
    if pending:
        for chunk in PublishingService._split_text(render_model_text(str(pending['result_text'])), 3900):
            await message.answer(chunk)
        await queries.mark_analysis_delivered(int(pending['id']), int(user['id']))
        await queries.set_free_analysis_used(int(user['id']))
        await state.clear()
        await message.answer(
            '<b>Это разбор, который был подготовлен раньше и ещё не был выдан.</b>',
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return
    await state.clear()
    free_available = bool(user and not user.get('used_free_analysis'))
    if source == 'site':
        await state.update_data(posts=[])
        await state.set_state(AnalysisStates.collecting_posts)
        await message.answer(
            '<b>Ты пришел проверить пост через KonturSMM.</b>\n\n'
            'Пришли текст Telegram-поста - я покажу, насколько цепляет начало, где есть вода, '
            'почему текст могут не дочитать и как его усилить.\n\n'
            + ('Первый анализ - бесплатно.' if free_available else 'Бесплатный разбор уже использован; для нового понадобится доступ.'),
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return
    if source == 'email':
        await state.update_data(posts=[])
        await state.set_state(AnalysisStates.collecting_posts)
        await message.answer(
            '<b>Ты пришел за чек-листом “17 причин, почему Telegram-посты не дочитывают”.</b>\n\n'
            'Короткая версия: слабое начало, долгий разгон, мало конкретики, нет понятной пользы, '
            'сложная структура, формальный CTA и финал без действия.\n\n'
            'Можешь сразу проверить свой пост. '
            + ('Первый анализ бесплатный.' if free_available else 'Для повторного анализа понадобится доступ.'),
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return
    if source == 'tg_channel':
        await state.update_data(posts=[])
        await state.set_state(AnalysisStates.collecting_posts)
        await message.answer(
            '<b>Ты пришел из канала KonturSMM.</b>\n\n'
            + (
                'Можешь протестировать бесплатный анализ Telegram-поста. '
                if free_available
                else 'Можешь снова разобрать Telegram-пост с активным доступом. '
            )
            + 'Пришли текст - я покажу, где пост теряет внимание.',
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return
    if source == 'payment_success':
        await message.answer(
            '<b>Если оплата уже прошла, лимиты начислятся после серверного подтверждения Robokassa.</b>\n\n'
            'Проверь раздел “Результаты” или статус последнего платежа.',
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return

    await message.answer(WELCOME_TEXT, reply_markup=free_analysis_keyboard() if free_available else None)
    await message.answer(MENU_TEXT, reply_markup=main_menu_keyboard(is_admin=is_admin))


def _parse_start_payload(args: str | None) -> tuple[str, str | None, str | None]:
    raw = (args or '').strip().lower()
    if not raw:
        return 'direct', None, None
    mapping = {
        'site': ('site', 'site', None),
        'email_leadmagnet': ('email', 'email', 'leadmagnet'),
        'tg_channel': ('tg_channel', 'telegram', 'channel'),
        'payment_success': ('payment_success', None, None),
        'free_analysis': ('direct', None, 'free_analysis'),
    }
    return mapping.get(raw, (raw[:64], None, None))
