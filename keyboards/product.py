from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def channel_menu_keyboard(connected: bool, profile_complete: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not connected:
        rows.append([InlineKeyboardButton(text='Подключить канал', callback_data='channel:connect')])
    else:
        rows.append([InlineKeyboardButton(text='Обновить права', callback_data='channel:permissions')])
        if profile_complete:
            rows.append([InlineKeyboardButton(text='Изменить настройки', callback_data='channel:profile')])
        else:
            rows.append([InlineKeyboardButton(text='Настроить канал', callback_data='channel:profile')])
        rows.append([InlineKeyboardButton(text='Часовой пояс', callback_data='channel:timezone')])
        rows.append([InlineKeyboardButton(text='Отключить канал', callback_data='channel:disconnect')])
    rows.append([InlineKeyboardButton(text='Тарифы', callback_data='payment:manage')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def timezone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Москва', callback_data='channel:tz:Europe/Moscow')],
            [InlineKeyboardButton(text='Екатеринбург', callback_data='channel:tz:Asia/Yekaterinburg')],
            [InlineKeyboardButton(text='Новосибирск', callback_data='channel:tz:Asia/Novosibirsk')],
            [InlineKeyboardButton(text='Владивосток', callback_data='channel:tz:Asia/Vladivostok')],
        ]
    )


def create_menu_keyboard(voice_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text='Готовый пост', callback_data='create:post')],
        [InlineKeyboardButton(text='Идеи', callback_data='create:ideas')],
        [InlineKeyboardButton(text='Улучшить текст', callback_data='create:rewrite')],
        [InlineKeyboardButton(text='CTA', callback_data='create:cta')],
    ]
    if voice_enabled:
        rows.append([InlineKeyboardButton(text='Голосовое → пост', callback_data='create:voice')])
    rows.append([InlineKeyboardButton(text='Мои черновики', callback_data='draft:list')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_actions_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text='Усилить', callback_data=f'draft:improve:{draft_id}'),
                InlineKeyboardButton(text='Переделать', callback_data=f'draft:redo:{draft_id}'),
            ],
            [InlineKeyboardButton(text='Редактировать вручную', callback_data=f'draft:edit:{draft_id}')],
            [
                InlineKeyboardButton(text='Опубликовать', callback_data=f'draft:publish:{draft_id}'),
                InlineKeyboardButton(text='Запланировать', callback_data=f'draft:schedule:{draft_id}'),
            ],
            [InlineKeyboardButton(text='Добавить изображение', callback_data=f'draft:image:{draft_id}')],
        ]
    )


def drafts_keyboard(drafts: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for draft in drafts:
        preview = str(draft.get('content_text') or '').replace('\n', ' ').strip()
        if len(preview) > 42:
            preview = preview[:39] + '...'
        if draft.get('status') == 'review':
            preview = 'Проверить публикацию: ' + preview
        rows.append([InlineKeyboardButton(text=preview or f"Черновик #{draft['id']}", callback_data=f"draft:view:{draft['id']}")])
    rows.append([InlineKeyboardButton(text='Создать новый', callback_data='create:post')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plan_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Составить план на 7 дней', callback_data='plan:generate')],
            [InlineKeyboardButton(text='Запланированные посты', callback_data='plan:list')],
            [InlineKeyboardButton(text='Черновики', callback_data='draft:list')],
        ]
    )


def schedules_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [InlineKeyboardButton(text=f"Отменить #{item['id']}", callback_data=f"schedule:cancel:{item['id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def analysis_menu_keyboard(
    channel_ready: bool,
    topic_intercept: bool,
    expert_available: bool = False,
    sources_enabled: bool = False,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text='Разобрать посты', callback_data='analysis:posts')]]
    if channel_ready:
        rows.append([InlineKeyboardButton(text='Разобрать мой канал', callback_data='analysis:channel')])
    if topic_intercept:
        rows.append([InlineKeyboardButton(text='Перехватить тему', callback_data='analysis:intercept')])
    if sources_enabled:
        rows.append([InlineKeyboardButton(text='Источники тем', callback_data='analysis:sources')])
    if expert_available:
        rows.append([InlineKeyboardButton(text='Проверка специалистом', callback_data='analysis:expert')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def competitor_sources_keyboard(sources: list[dict], monitor_settings: dict) -> InlineKeyboardMarkup:
    notify_labels = {
        'strong': '🔥 Уведомления: сильные',
        'all': '🔔 Уведомления: все новые',
        'off': '🔕 Уведомления выключены',
    }
    notify_mode = str(monitor_settings.get('notify_mode') or 'strong')
    pulse_enabled = bool(monitor_settings.get('pulse_enabled'))
    plan_enabled = bool(monitor_settings.get('weekly_plan_enabled'))
    rows = [
        [InlineKeyboardButton(text='➕ Добавить источник', callback_data='analysis:source_add')],
        [
            InlineKeyboardButton(text='🔄 Проверить сейчас', callback_data='analysis:sources_sync'),
            InlineKeyboardButton(text='📡 Пульс за 7 дней', callback_data='analysis:pulse_now'),
        ],
        [
            InlineKeyboardButton(
                text=notify_labels.get(notify_mode, notify_labels['strong']),
                callback_data='analysis:notify_cycle',
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📡 Пульс недели: {'включён' if pulse_enabled else 'выключен'}",
                callback_data='analysis:pulse_toggle',
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🗓 AI-план недели: {'включён' if plan_enabled else 'выключен'}",
                callback_data='analysis:plan_toggle',
            )
        ],
        [InlineKeyboardButton(text='🗓 Собрать план сейчас', callback_data='analysis:competitor_plan_now')],
    ]
    for source in sources:
        label = source.get('title') or source.get('username') or f"Источник #{source['id']}"
        if len(str(label)) > 28:
            label = str(label)[:25] + '...'
        rows.append(
            [InlineKeyboardButton(text=f'✕ {label}', callback_data=f"analysis:source_remove:{source['id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def competitor_alert_keyboard(post_id: int, post_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Открыть пост', url=post_url)],
            [InlineKeyboardButton(text='Взять тему без копирования', callback_data=f'analysis:intercept_saved:{post_id}')],
        ]
    )


def competitor_digest_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Собрать план по сигналам', callback_data='analysis:competitor_plan_now')],
            [InlineKeyboardButton(text='Настроить источники', callback_data='analysis:sources')],
        ]
    )


def expert_review_keyboard(channel_available: bool, post_available: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if post_available:
        rows.append([InlineKeyboardButton(text='Разбор поста человеком', callback_data='analysis:expert_post')])
    if channel_available:
        rows.append([InlineKeyboardButton(text='Разбор канала человеком', callback_data='analysis:expert_channel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def analysis_collect_keyboard(posts_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f'Начать разбор ({posts_count})', callback_data='analysis:run')],
            [InlineKeyboardButton(text='Добавить ещё пост', callback_data='analysis:add')],
            [InlineKeyboardButton(text='Отмена', callback_data='analysis:cancel')],
        ]
    )


def trial_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Получить 24 часа бесплатно', callback_data='trial:start')],
            [InlineKeyboardButton(text='Посмотреть тарифы', callback_data='payment:manage')],
        ]
    )


def trial_membership_keyboard(channel_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Подписаться на KonturSMM', url=channel_link)],
            [InlineKeyboardButton(text='Проверить подписку', callback_data='trial:verify')],
        ]
    )


def trial_continue_keyboard(step: str) -> InlineKeyboardMarkup:
    labels = {
        'channel': ('Подключить канал', 'channel:connect'),
        'profile': ('Настроить канал', 'channel:profile'),
        'activate': ('Активировать 24 часа', 'trial:activate'),
    }
    label, callback = labels[step]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=callback)]])


def access_required_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='Попробовать 24 часа бесплатно', callback_data='trial:start')],
            [InlineKeyboardButton(text='Тарифы', callback_data='payment:manage')],
        ]
    )


def results_keyboard(support_username: str) -> InlineKeyboardMarkup:
    username = support_username.strip().lstrip('@')
    rows = [[InlineKeyboardButton(text='Тарифы', callback_data='payment:manage')]]
    if username:
        rows.append([InlineKeyboardButton(text='Поддержка', url=f'https://t.me/{username}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
