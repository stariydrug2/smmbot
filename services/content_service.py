from __future__ import annotations

from typing import Any

from database.queries import QueryService
from services import prompt_builder
from services.memory_service import MemoryService
from services.openai_service import OpenAIService
from services.prompt_templates import SYSTEM_PROMPT_RU


class ContentService:
    def __init__(self, queries: QueryService, openai_service: OpenAIService, memory_service: MemoryService) -> None:
        self.queries = queries
        self.openai_service = openai_service
        self.memory_service = memory_service

    async def _context(self, user_id: int) -> tuple[dict[str, Any] | None, str, list[str]]:
        ctx = await self.memory_service.collect_context(user_id)
        return ctx['profile'], str(ctx['summary']), list(ctx['examples'])

    async def generate(self, user_id: int, mode: str, user_request: str, source_type: str = 'text', **kwargs: Any) -> str:
        profile, summary, examples = await self._context(user_id)
        builders = {
            'content_plan': prompt_builder.build_content_plan_prompt,
            'post': prompt_builder.build_post_prompt,
            'series': prompt_builder.build_series_prompt,
            'rewrite': prompt_builder.build_rewrite_prompt,
            'cta': prompt_builder.build_cta_prompt,
            'story': prompt_builder.build_story_prompt,
            'visual': prompt_builder.build_visual_idea_prompt,
            'image_prompt': prompt_builder.build_image_prompt,
        }
        if mode not in builders:
            raise ValueError(f'Unknown generation mode: {mode}')
        prompt = builders[mode](profile, summary, examples, user_request, **kwargs)
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(user_id, mode, source_type, user_request, result, kwargs)
        return result

    async def analyze_examples(self, user_id: int, examples: list[str]) -> str:
        analysis = await self.openai_service.analyze_examples(examples)
        await self.queries.upsert_memory_summary(user_id, analysis)
        return analysis
