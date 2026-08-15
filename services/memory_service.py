from __future__ import annotations

from database.queries import QueryService
from database.product_repository import ProductRepository
from services.openai_service import OpenAIService


class MemoryService:
    def __init__(
        self,
        queries: QueryService,
        openai_service: OpenAIService,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self.queries = queries
        self.openai_service = openai_service
        self.product_repository = product_repository

    async def collect_context(self, user_id: int) -> dict[str, object]:
        profile = None
        channel = None
        if self.product_repository:
            channel = await self.product_repository.get_active_channel(user_id)
            if channel:
                channel_profile = await self.product_repository.get_channel_profile(int(channel['id']))
                if channel_profile and channel_profile.get('is_complete'):
                    profile = {
                        **channel_profile,
                        'person_name': '',
                        'brand_name': channel.get('title'),
                        'brand_description': channel_profile.get('project_description'),
                        'usage_goal': channel_profile.get('goals'),
                        'preferred_formats': channel_profile.get('content_rubrics'),
                        'forbidden_words': channel_profile.get('forbidden_phrases'),
                        'wants_images': 1,
                    }
        examples = await self.queries.get_user_examples(
            user_id,
            limit=5,
            channel_id=int(channel['id']) if channel else None,
        )
        if channel and not examples:
            examples = await self.queries.get_user_examples(user_id, limit=5)
        return {
            'profile': profile or await self.queries.get_brand_profile(user_id),
            'examples': examples,
            'summary': await self.queries.get_memory_summary(user_id),
            'history': await self.queries.get_generation_history(user_id, limit=3),
        }

    async def refresh_summary(self, user_id: int) -> str:
        context = await self.collect_context(user_id)
        raw = f"Профиль: {context['profile']}\n\nПримеры: {context['examples']}\n\nИстория: {context['history']}"
        summary = await self.openai_service.summarize_memory(raw)
        await self.queries.upsert_memory_summary(user_id, summary)
        return summary
