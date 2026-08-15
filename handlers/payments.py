from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

from database.queries import QueryService
from database.product_repository import ProductRepository
from keyboards.inline import payment_created_keyboard, payment_plans_keyboard, payments_history_keyboard
from services.payment_service import PaymentService
from services.subscription_service import SubscriptionService
from utils.formatting import format_payment_details, format_payment_history
from utils.helpers import escape_html
from utils.texts import PAYMENT_CREATED_TEXT, PAYMENT_HISTORY_EMPTY_TEXT, PAYMENT_MENU_TEXT

router = Router()


@router.callback_query(lambda c: c.data == 'payment:manage')
async def payment_manage(callback: CallbackQuery, queries: QueryService, subscription_service: SubscriptionService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    status = await subscription_service.get_status(int(user['id']))
    plans = await queries.get_subscription_plans()
    text = PAYMENT_MENU_TEXT
    if status.get('ends_at_human'):
        text += f"\n\n<b>Текущий статус:</b> {escape_html(str(status['status']))}\n<b>Действует до:</b> {escape_html(str(status['ends_at_human']))}"
    await callback.message.answer(text, reply_markup=payment_plans_keyboard(plans))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('payment:buy:'))
async def payment_buy(
    callback: CallbackQuery,
    queries: QueryService,
    payment_service: PaymentService,
    product_repository: ProductRepository,
) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    plan_code = callback.data.split(':')[-1]
    try:
        payment = await payment_service.create_payment_for_plan(int(user['id']), plan_code)
    except Exception as exc:
        await callback.message.answer(f"<b>Не удалось создать счёт.</b>\n\n{escape_html(str(exc))}")
        await callback.answer('Ошибка создания счёта', show_alert=True)
        return
    await callback.message.answer(
        PAYMENT_CREATED_TEXT.format(plan_title=escape_html(payment['plan_title']), price_rub=int(payment['amount'])),
        reply_markup=payment_created_keyboard(int(payment['id']), str(payment['invoice_url'])),
    )
    await product_repository.log_activity(
        'payment_invoice_created',
        user_id=int(user['id']),
        telegram_id=int(user['telegram_id']),
        username=user.get('username'),
        full_name=user.get('full_name'),
        payload={'payment_id': int(payment['id']), 'plan_code': payment.get('plan_code')},
    )
    await callback.answer('Счёт создан')


@router.callback_query(lambda c: c.data == 'payment:refresh_last')
async def payment_refresh_last(callback: CallbackQuery, queries: QueryService, payment_service: PaymentService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    payment = await queries.get_latest_pending_payment(int(user['id']))
    if not payment:
        await callback.answer('Нет ожидающего платежа', show_alert=True)
        return
    await _refresh_and_show(callback, payment_service, int(payment['id']))


@router.callback_query(lambda c: c.data and c.data.startswith('payment:refresh:'))
async def payment_refresh(callback: CallbackQuery, queries: QueryService, payment_service: PaymentService) -> None:
    if not callback.message or not callback.from_user:
        return
    payment_id = int(callback.data.split(':')[-1])
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    payment = await queries.get_payment(payment_id)
    if not user or not payment or int(payment['user_id']) != int(user['id']):
        await callback.answer('Платёж не найден', show_alert=True)
        return
    await _refresh_and_show(callback, payment_service, payment_id)


async def _refresh_and_show(callback: CallbackQuery, payment_service: PaymentService, payment_id: int) -> None:
    try:
        payment = await payment_service.refresh_payment_status(payment_id)
    except Exception as exc:
        await callback.message.answer(f"<b>Не удалось проверить статус.</b>\n\n{escape_html(str(exc))}")
        await callback.answer('Ошибка проверки', show_alert=True)
        return
    await callback.message.answer(format_payment_details(payment))
    await callback.answer('Статус обновлён')


@router.callback_query(lambda c: c.data == 'payment:history')
async def payment_history(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    payments = await queries.list_user_payments(int(user['id']), limit=20)
    if not payments:
        await callback.message.answer(PAYMENT_HISTORY_EMPTY_TEXT)
        await callback.answer()
        return
    await callback.message.answer(format_payment_history(payments), reply_markup=payments_history_keyboard(payments))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith('payment:view:'))
async def payment_view(callback: CallbackQuery, queries: QueryService) -> None:
    if not callback.from_user or not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    payment_id = int(callback.data.split(':')[-1])
    payments = await queries.list_user_payments(int(user['id']), limit=50)
    payment = next((item for item in payments if int(item['id']) == payment_id), None)
    if not payment:
        await callback.answer('Платёж не найден', show_alert=True)
        return
    await callback.message.answer(format_payment_details(payment))
    await callback.answer()
