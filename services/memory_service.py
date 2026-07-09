from __future__ import annotations

from database.queries import QueryService
from services.openai_service import OpenAIService


class MemoryService:
    def __init__(self, queries: QueryService, openai_service: OpenAIService) -> None:
        self.queries = queries
        self.openai_service = openai_service

    async def collect_context(self, user_id: int) -> dict[str, object]:
        return {
            'profile': await self.queries.get_brand_profile(user_id),
            'examples': await self.queries.get_user_examples(user_id, limit=5),
            'summary': await self.queries.get_memory_summary(user_id),
            'history': await self.queries.get_generation_history(user_id, limit=3),
        }

    async def refresh_summary(self, user_id: int) -> str:
        context = await self.collect_context(user_id)
        raw = f"Профиль: {context['profile']}\n\nПримеры: {context['examples']}\n\nИстория: {context['history']}"
        summary = await self.openai_service.summarize_memory(raw)
        await self.queries.upsert_memory_summary(user_id, summary)
        return summary
