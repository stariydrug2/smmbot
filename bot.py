from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database.db import Database
from database.queries import QueryService
from handlers import register_routers
from middlewares.subscription_middleware import SubscriptionMiddleware
from middlewares.throttle_middleware import ThrottleMiddleware
from services.content_service import ContentService
from services.image_service import ImageService
from services.memory_service import MemoryService
from services.openai_service import OpenAIService
from services.subscription_service import SubscriptionService
from services.transcription_service import TranscriptionService


async def main() -> None:
    settings.validate()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )

    db = Database(settings.database_path)
    await db.connect()
    await db.init_db()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    queries = QueryService(db)
    openai_service = OpenAIService(api_key=settings.openai_api_key, model=settings.openai_text_model)
    image_service = ImageService(api_key=settings.openai_api_key, model=settings.openai_image_model)
    transcription_service = TranscriptionService(api_key=settings.openai_api_key, model=settings.openai_transcribe_model)
    memory_service = MemoryService(queries=queries, openai_service=openai_service)
    subscription_service = SubscriptionService(queries=queries, settings=settings)
    content_service = ContentService(queries=queries, openai_service=openai_service, memory_service=memory_service)

    dp.workflow_data.update(
        db=db,
        queries=queries,
        settings=settings,
        openai_service=openai_service,
        image_service=image_service,
        transcription_service=transcription_service,
        memory_service=memory_service,
        subscription_service=subscription_service,
        content_service=content_service,
    )

    dp.message.middleware(ThrottleMiddleware())
    dp.callback_query.middleware(ThrottleMiddleware())
    dp.message.middleware(SubscriptionMiddleware(queries=queries, settings=settings))
    dp.callback_query.middleware(SubscriptionMiddleware(queries=queries, settings=settings))

    register_routers(dp)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())
