from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def subscription_keyboard(channel_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='📢 Подписаться', url=channel_link)],
            [InlineKeyboardButton(text='✅ Проверить подписку', callback_data='check_subscription')],
        ]
    )


def post_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='🔁 Переделать', callback_data='content:redo'),
                InlineKeyboardButton(text='✏️ Сделать короче', callback_data='content:shorter'),
            ],
            [
                InlineKeyboardButton(text='🔥 Сделать сильнее', callback_data='content:stronger'),
                InlineKeyboardButton(text='🧠 Сделать экспертнее', callback_data='content:expert'),
            ],
            [
                InlineKeyboardButton(text='💬 Сделать мягче', callback_data='content:softer'),
                InlineKeyboardButton(text='📌 Добавить CTA', callback_data='content:cta'),
            ],
            [
                InlineKeyboardButton(text='🖼 Идея визуала', callback_data='content:visual'),
                InlineKeyboardButton(text='💾 Сохранить', callback_data='content:save'),
            ],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')],
        ]
    )


def history_keyboard(records: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for record in records:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📄 {record['generation_type']} · #{record['id']}",
                    callback_data=f"history:view:{record['id']}",
                ),
                InlineKeyboardButton(text='🗑', callback_data=f"history:delete:{record['id']}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 Подписка', callback_data='payment:manage')],
            [InlineKeyboardButton(text='🧾 История оплат', callback_data='payment:history')],
            [InlineKeyboardButton(text='✏️ Имя', callback_data='profile:person_name')],
            [InlineKeyboardButton(text='🏷 Бренд', callback_data='profile:brand_name')],
            [InlineKeyboardButton(text='🧾 Описание', callback_data='profile:brand_description')],
            [InlineKeyboardButton(text='🎯 Цель', callback_data='profile:usage_goal')],
            [InlineKeyboardButton(text='👥 Аудитория', callback_data='profile:target_audience')],
            [InlineKeyboardButton(text='🗣 Tone of voice', callback_data='profile:tone_of_voice')],
            [InlineKeyboardButton(text='📏 Длина постов', callback_data='profile:post_length')],
            [InlineKeyboardButton(text='🧩 Форматы', callback_data='profile:preferred_formats')],
            [InlineKeyboardButton(text='🚫 Запрещённые слова', callback_data='profile:forbidden_words')],
            [InlineKeyboardButton(text='📝 Примеры постов', callback_data='profile:examples')],
            [InlineKeyboardButton(text='🧠 Обновить память', callback_data='profile:refresh_memory')],
            [InlineKeyboardButton(text='🗑 Очистить историю', callback_data='profile:clear_history')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')],
        ]
    )


def content_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Пересобрать план', callback_data='plan:redo')],
            [InlineKeyboardButton(text='💾 Сохранить', callback_data='content:save')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')],
        ]
    )


def voice_after_transcription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='📝 Сделать пост', callback_data='voice:post')],
            [InlineKeyboardButton(text='🧵 Сделать серию', callback_data='voice:series')],
            [InlineKeyboardButton(text='🗓 Сделать контент-план', callback_data='voice:plan')],
            [InlineKeyboardButton(text='📣 Story-анонс', callback_data='voice:story')],
            [InlineKeyboardButton(text='💾 Сохранить как материал', callback_data='voice:save')],
        ]
    )


def photo_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='📝 Придумать пост', callback_data='photo:post')],
            [InlineKeyboardButton(text='✍️ Придумать подпись', callback_data='photo:caption')],
            [InlineKeyboardButton(text='🎨 Идея визуальной серии', callback_data='photo:visual_series')],
            [InlineKeyboardButton(text='🧠 Проанализировать настроение', callback_data='photo:mood')],
            [InlineKeyboardButton(text='🖼 Сгенерировать изображение', callback_data='photo:generate')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')],
        ]
    )


def visual_text_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🖼 Сгенерировать изображение', callback_data='visual_text:generate')],
            [InlineKeyboardButton(text='🎨 Только идея визуала', callback_data='visual_text:idea')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')],
        ]
    )


def payment_plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💳 {plan['title']} · {plan['price_rub']} ₽",
                    callback_data=f"payment:buy:{plan['code']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text='🔄 Проверить последний платёж', callback_data='payment:refresh_last')])
    rows.append([InlineKeyboardButton(text='🧾 История оплат', callback_data='payment:history')])
    rows.append([InlineKeyboardButton(text='⬅️ В меню', callback_data='go:menu')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_created_keyboard(payment_id: int, payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 Перейти к оплате', url=payment_url)],
            [InlineKeyboardButton(text='🔄 Проверить статус', callback_data=f'payment:refresh:{payment_id}')],
            [InlineKeyboardButton(text='📦 Другой тариф', callback_data='payment:manage')],
            [InlineKeyboardButton(text='👤 В профиль', callback_data='payment:profile')],
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
