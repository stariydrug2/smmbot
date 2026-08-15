from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PLAN_ICONS = {
    'start': '🚀',
    'content_week': '📅',
    'restart': '🔥',
    'full_access': '💼',
    'premium': '👑',
}


def free_analysis_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔎 Проверить пост бесплатно', callback_data='analysis:posts')],
            [InlineKeyboardButton(text='✍️ Создать пост', callback_data='create:post')],
            [InlineKeyboardButton(text='💳 Посмотреть тарифы', callback_data='payment:manage')],
        ]
    )


def payment_plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        icon = PLAN_ICONS.get(str(plan.get('code')), '💳')
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {plan['title']} · {plan['price_rub']} ₽",
                    callback_data=f"payment:buy:{plan['code']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text='🔄 Проверить последний платёж', callback_data='payment:refresh_last')])
    rows.append([InlineKeyboardButton(text='🧾 История оплат', callback_data='payment:history')])
    rows.append([InlineKeyboardButton(text='⬅️ В меню', callback_data='nav:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_created_keyboard(payment_id: int, payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 Перейти к оплате', url=payment_url)],
            [InlineKeyboardButton(text='🔄 Проверить статус', callback_data=f'payment:refresh:{payment_id}')],
            [InlineKeyboardButton(text='📦 Другой тариф', callback_data='payment:manage')],
            [InlineKeyboardButton(text='⬅️ В главное меню', callback_data='nav:main')],
        ]
    )


def payments_history_keyboard(payments: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for payment in payments[:10]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🧾 {payment.get('plan_title') or payment.get('plan_code') or 'Платёж'} · #{payment['id']}",
                    callback_data=f"payment:view:{payment['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text='⬅️ К тарифам', callback_data='payment:manage')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
