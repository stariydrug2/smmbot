from __future__ import annotations

from aiogram.types import (
    ChatAdministratorRights,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)


MAIN_MENU_BUTTONS = {
    '📣 Мой канал',
    '✍️ Создать',
    '🗓 План',
    '🔎 Анализ',
    '📈 Результаты',
    '🛠 Админка',
}


def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text='📣 Мой канал'), KeyboardButton(text='✍️ Создать')],
        [KeyboardButton(text='🗓 План'), KeyboardButton(text='🔎 Анализ')],
        [KeyboardButton(text='📈 Результаты')],
    ]
    if is_admin:
        rows.append([KeyboardButton(text='🛠 Админка')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def channel_connect_keyboard() -> ReplyKeyboardMarkup:
    rights = ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=False,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=True,
        can_edit_messages=True,
    )
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text='📣 Выбрать канал',
                    request_chat=KeyboardButtonRequestChat(
                        request_id=701,
                        chat_is_channel=True,
                        bot_administrator_rights=rights,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton(text='📣 Мой канал')],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
