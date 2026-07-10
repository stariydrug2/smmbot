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
            'ideas': prompt_builder.build_ideas_prompt,
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

    async def analyze_post(self, user_id: int, post_text: str, post_goal: str | None) -> str:
        profile, summary, examples = await self._context(user_id)
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: сделай качественный разбор Telegram-поста или нескольких постов.\n"
            "Пиши как сильный SMM-редактор: честно, конкретно, без натягивания проблем. "
            "Если текст хороший, сначала подчеркни, что уже работает, и только потом предложи усиления.\n"
            "Не обесценивай автора и не пиши, что всё плохо, если это не так. "
            "Не переписывай весь пост целиком: для бесплатного разбора дай точечные правки "
            "и один короткий пример более сильного начала или CTA.\n\n"
            f"Цель поста: {post_goal or 'не указана'}\n\n"
            f"Пост пользователя:\n{post_text}\n\n"
            "Если прислано несколько постов, анализируй их как подборку: найди общие закономерности, "
            "отметь самый сильный материал и один главный общий риск. Не делай длинный отдельный разбор каждого поста.\n\n"
            "Формат ответа:\n"
            "Оценка: X/10\n"
            "Что уже работает:\n"
            "Что можно усилить:\n"
            "Где может теряться внимание:\n"
            "Структура и логика:\n"
            "Начало:\n"
            "CTA:\n"
            "Если постов несколько - общий вывод по серии:\n"
            "Пример точечного усиления:\n"
            "Вывод:"
        )
        return await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)

    async def analyze_examples(self, user_id: int, examples: list[str]) -> str:
        analysis = await self.openai_service.analyze_examples(examples)
        await self.queries.upsert_memory_summary(user_id, analysis)
        return analysis
