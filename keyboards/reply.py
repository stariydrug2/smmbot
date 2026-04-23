from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text='✍️ Создать контент'), KeyboardButton(text='🗓 Контент-план')],
        [KeyboardButton(text='🎙 Пост из голосового'), KeyboardButton(text='🖼 Фото / визуал')],
        [KeyboardButton(text='💳 Подписка'), KeyboardButton(text='👤 Личный кабинет')],
        [KeyboardButton(text='🕘 История'), KeyboardButton(text='ℹ️ Помощь')],
    ]
    if is_admin:
        rows.append([KeyboardButton(text='🛠 Админка')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def onboarding_lengths_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Короткие')],
            [KeyboardButton(text='Средние')],
            [KeyboardButton(text='Развернутые')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def yes_no_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text='Да'), KeyboardButton(text='Нет')]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def content_modes_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='💡 Идея поста'), KeyboardButton(text='📝 Готовый пост')],
            [KeyboardButton(text='🧵 Серия постов'), KeyboardButton(text='♻️ Рерайт')],
            [KeyboardButton(text='📌 CTA'), KeyboardButton(text='📣 Story-анонс')],
            [KeyboardButton(text='⬅️ Назад')],
        ],
        resize_keyboard=True,
    )
