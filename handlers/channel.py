from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from keyboards.product import timezone_keyboard, trial_continue_keyboard
from keyboards.reply import channel_connect_keyboard, main_menu_keyboard
from services.channel_service import ChannelService
from services.trial_service import TrialService
from states.product_states import ChannelProfileStates
from utils.helpers import escape_html

router = Router()


@router.callback_query(F.data == 'channel:connect')
async def connect_prompt(callback: CallbackQuery, settings: Settings) -> None:
    if not callback.message:
        return
    if not settings.feature_channel_connect:
        await callback.answer('Подключение каналов временно выключено', show_alert=True)
        return
    await callback.message.answer(
        '<b>Подключение канала</b>\n\n'
        'Нажмите кнопку ниже и выберите канал. Telegram предложит добавить бота администратором. '
        'Оставьте права на публикацию и редактирование сообщений.',
        reply_markup=channel_connect_keyboard(),
    )
    await callback.answer()


@router.message(F.chat_shared)
async def channel_shared(
    message: Message,
    bot: Bot,
    queries: QueryService,
    channel_service: ChannelService,
    settings: Settings,
) -> None:
    if not message.from_user or not message.chat_shared or message.chat_shared.request_id != 701:
        return
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return
    try:
        channel = await channel_service.connect(
            bot,
            user_id=int(user['id']),
            telegram_user_id=message.from_user.id,
            chat_id=int(message.chat_shared.chat_id),
        )
    except Exception as exc:
        await message.answer(
            f"<b>Канал не подключён.</b>\n\n{escape_html(str(exc))}",
            reply_markup=channel_connect_keyboard(),
        )
        return
    await message.answer(
        f"<b>Канал «{escape_html(str(channel['title']))}» подключён.</b>\n\n"
        'Теперь ответьте на несколько вопросов, чтобы тексты звучали как часть вашего канала.',
        reply_markup=main_menu_keyboard(message.from_user.id in settings.admin_ids),
    )
    await channel_service.repository.log_activity(
        'channel_connected',
        user_id=int(user['id']),
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        payload={'channel_id': int(channel['id'])},
    )
    await message.answer(
        'Следующий шаг — короткая настройка канала.',
        reply_markup=trial_continue_keyboard('profile'),
    )


@router.callback_query(F.data == 'channel:permissions')
async def refresh_permissions(
    callback: CallbackQuery,
    bot: Bot,
    queries: QueryService,
    product_repository: ProductRepository,
    channel_service: ChannelService,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not channel:
        await callback.answer('Канал не подключён', show_alert=True)
        return
    try:
        can_post, can_edit = await channel_service.refresh_permissions(bot, channel)
    except Exception:
        await callback.answer('Не удалось проверить. Убедитесь, что бот добавлен в канал.', show_alert=True)
        return
    await callback.answer('Права обновлены')
    await callback.message.answer(
        f"<b>Публикация:</b> {'доступна' if can_post else 'нет права'}\n"
        f"<b>Редактирование:</b> {'доступно' if can_edit else 'нет права'}"
    )


@router.callback_query(F.data == 'channel:disconnect')
async def disconnect_channel(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not user or not channel:
        await callback.answer('Канал уже отключён', show_alert=True)
        return
    await product_repository.disconnect_channel(int(channel['id']), int(user['id']))
    if callback.message:
        await callback.message.answer('Канал отключён. Черновики и история сохранены.')
    await callback.answer()


@router.callback_query(F.data == 'channel:timezone')
async def timezone_prompt(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer(
            '<b>Часовой пояс публикаций</b>\n\nВыберите город с вашим временем.',
            reply_markup=timezone_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith('channel:tz:'))
async def timezone_selected(
    callback: CallbackQuery,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    timezone_name = callback.data.split(':', 2)[2]
    if not user or not channel or not await product_repository.update_channel_timezone(
        int(channel['id']), int(user['id']), timezone_name
    ):
        await callback.answer('Не удалось изменить часовой пояс', show_alert=True)
        return
    if callback.message:
        await callback.message.answer(f'Часовой пояс изменён: <b>{escape_html(timezone_name)}</b>.')
    await callback.answer('Сохранено')


@router.callback_query(F.data == 'channel:profile')
async def profile_start(
    callback: CallbackQuery,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
) -> None:
    if not callback.message:
        return
    user = await queries.get_user_by_telegram_id(callback.from_user.id)
    channel = await product_repository.get_active_channel(int(user['id'])) if user else None
    if not channel:
        await callback.answer('Сначала подключите канал', show_alert=True)
        return
    await state.clear()
    await state.update_data(channel_id=int(channel['id']))
    await state.set_state(ChannelProfileStates.project)
    await callback.message.answer(
        '<b>1 из 6. О чём канал?</b>\n\nОпишите нишу, проект и продукты или услуги одним сообщением.'
    )
    await callback.answer()


@router.message(ChannelProfileStates.project, F.text)
async def profile_project(message: Message, state: FSMContext) -> None:
    await state.update_data(project=message.text.strip())
    await state.set_state(ChannelProfileStates.audience)
    await message.answer('<b>2 из 6. Кто аудитория?</b>\n\nКому вы пишете и что для этих людей важно?')


@router.message(ChannelProfileStates.audience, F.text)
async def profile_audience(message: Message, state: FSMContext) -> None:
    await state.update_data(audience=message.text.strip())
    await state.set_state(ChannelProfileStates.voice)
    await message.answer(
        '<b>3 из 6. Как должен звучать канал?</b>\n\nОпишите тон, желаемую длину постов, эмодзи и заголовки.'
    )


@router.message(ChannelProfileStates.voice, F.text)
async def profile_voice(message: Message, state: FSMContext) -> None:
    await state.update_data(voice=message.text.strip())
    await state.set_state(ChannelProfileStates.topics)
    await message.answer('<b>4 из 6. Темы и рубрики</b>\n\nЧто публикуете регулярно и каких тем лучше избегать?')


@router.message(ChannelProfileStates.topics, F.text)
async def profile_topics(message: Message, state: FSMContext) -> None:
    await state.update_data(topics=message.text.strip())
    await state.set_state(ChannelProfileStates.goals)
    await message.answer('<b>5 из 6. Цель канала</b>\n\nКакого действия ждёте от читателя? Какие CTA обычно используете?')


@router.message(ChannelProfileStates.goals, F.text)
async def profile_goals(message: Message, state: FSMContext) -> None:
    await state.update_data(goals=message.text.strip())
    await state.set_state(ChannelProfileStates.examples)
    await message.answer(
        '<b>6 из 6. Примеры</b>\n\nПришлите 3–5 характерных постов одним сообщением, разделив их строкой <code>---</code>. '
        'Если примеров пока нет, напишите «Пропустить».'
    )


@router.message(ChannelProfileStates.examples, F.text)
async def profile_examples(
    message: Message,
    state: FSMContext,
    queries: QueryService,
    product_repository: ProductRepository,
    trial_service: TrialService,
) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    user = await queries.get_user_by_telegram_id(message.from_user.id)
    channel_id = int(data['channel_id'])
    project = str(data.get('project') or '')
    topics = str(data.get('topics') or '')
    goals = str(data.get('goals') or '')
    await product_repository.update_channel_profile(
        channel_id,
        niche=project,
        project_description=project,
        products=project,
        target_audience=str(data.get('audience') or ''),
        tone_of_voice=str(data.get('voice') or ''),
        post_length=str(data.get('voice') or ''),
        emoji_style=str(data.get('voice') or ''),
        heading_style=str(data.get('voice') or ''),
        key_topics=topics,
        content_rubrics=topics,
        undesired_topics='',
        goals=goals,
        typical_cta=goals,
        is_complete=1,
    )
    raw_examples = message.text.strip()
    if raw_examples.lower() != 'пропустить' and user:
        await queries.clear_user_examples(int(user['id']), channel_id)
        examples = [item.strip() for item in raw_examples.split('---') if item.strip()][:5]
        for example in examples:
            await queries.add_user_example(int(user['id']), example, channel_id)
    await state.clear()
    await message.answer('<b>Канал настроен.</b>\n\nТеперь генерации будут учитывать эту информацию.')
    if user:
        await product_repository.log_activity(
            'channel_profile_completed',
            user_id=int(user['id']),
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            payload={'channel_id': channel_id},
        )
        ready = await trial_service.readiness(int(user['id']))
        if ready['membership_verified'] and ready['trial'].get('status') == 'none':
            await message.answer(
                'Все условия выполнены. Запустите пробный доступ тогда, когда будете готовы работать.',
                reply_markup=trial_continue_keyboard('activate'),
            )


@router.channel_post()
async def remember_channel_post(message: Message, product_repository: ProductRepository) -> None:
    channel = await product_repository.get_channel_by_chat_id(message.chat.id)
    if not channel or channel.get('status') != 'active':
        return
    text = (message.text or message.caption or '').strip()
    if not text:
        return
    published_at = message.date.isoformat() if message.date else None
    await product_repository.save_channel_post(
        channel_id=int(channel['id']),
        telegram_message_id=message.message_id,
        content_text=text,
        published_at=published_at,
    )
