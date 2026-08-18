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
        metadata = {**kwargs, 'provider': self.openai_service.last_provider}
        await self.queries.add_generation_history(user_id, mode, source_type, user_request, result, metadata)
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

    async def improve_draft(self, user_id: int, current_text: str, instruction: str) -> str:
        profile, summary, examples = await self._context(user_id)
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: отредактируй готовый Telegram-пост по инструкции пользователя. "
            "Сохрани факты и исходный смысл. Верни только обновлённый текст, готовый к публикации.\n\n"
            f"Инструкция: {instruction}\n\nТекущий текст:\n{current_text}"
        )
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(
            user_id,
            'improve',
            'draft',
            current_text,
            result,
            {'instruction': instruction, 'provider': self.openai_service.last_provider},
        )
        return result

    async def intercept_topic(self, user_id: int, source_post: str) -> str:
        profile, summary, examples = await self._context(user_id)
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: пользователь прислал чужой или найденный пост. Не копируй формулировки, "
            "структуру и уникальные примеры. Выдели саму тему и предложи 5 оригинальных углов, "
            "под которыми её можно раскрыть для канала пользователя.\n\n"
            f"Исходный пост:\n{source_post}\n\n"
            "Для каждого варианта дай: угол, главную мысль, короткое начало и пользу читателю."
        )
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(
            user_id,
            'topic_intercept',
            'text',
            source_post,
            result,
            {'provider': self.openai_service.last_provider},
        )
        return result

    async def competitor_pulse(self, user_id: int, posts: list[dict[str, Any]]) -> str:
        profile, summary, examples = await self._context(user_id)
        material = self._competitor_material(posts, limit=30)
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: подготовь короткий еженедельный «Пульс ниши» по открытым публикациям "
            "выбранных Telegram-каналов. Найди 3–5 повторяющихся или усиливающихся тем и объясни, "
            "какие конкретные публикации и метрики дают такой сигнал. Не называй тему растущей, "
            "если данных недостаточно. Не выдумывай охваты, динамику подписчиков, продажи и ER. "
            "Не копируй чужие формулировки и не пересказывай посты целиком.\n\n"
            f"ДАННЫЕ ЗА 7 ДНЕЙ:\n{material}\n\n"
            "Формат: 1) Что привлекает внимание; 2) Сильные публикации и почему они выделяются; "
            "3) Какие темы уже перегреты; 4) Три возможности для оригинального контента пользователя. "
            "Пиши конкретно и компактно."
        )
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(
            user_id,
            'competitor_pulse',
            'competitor_posts',
            material,
            result,
            {'posts_count': min(len(posts), 30), 'provider': self.openai_service.last_provider},
        )
        return result

    async def competitor_content_plan(self, user_id: int, posts: list[dict[str, Any]]) -> str:
        profile, summary, examples = await self._context(user_id)
        material = self._competitor_material(posts, limit=24)
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: составь оригинальный контент-план Telegram-канала пользователя на 7 дней, "
            "используя сигналы ниши ниже только как исследовательский материал. Не копируй темы "
            "буквально, формулировки, структуру и уникальные примеры конкурентов. План должен "
            "усиливать собственную экспертизу и цели канала пользователя. Не выдумывай метрики.\n\n"
            f"СИГНАЛЫ НИШИ ЗА 7 ДНЕЙ:\n{material}\n\n"
            "Сбалансируй план: актуальные углы, собственная экспертность, вовлечение и уместная "
            "продажа. Для каждого дня дай: тему, оригинальный угол, формат, цель, основную мысль, "
            "первую фразу и CTA. Отдельно укажи, какой сигнал ниши использован и как избежать копирования."
        )
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(
            user_id,
            'content_plan',
            'competitor_weekly',
            material,
            result,
            {'posts_count': min(len(posts), 24), 'provider': self.openai_service.last_provider},
        )
        return result

    @staticmethod
    def _competitor_material(posts: list[dict[str, Any]], limit: int) -> str:
        blocks: list[str] = []
        for post in posts[:limit]:
            source = post.get('source_title') or f"@{post.get('username') or 'channel'}"
            score = float(post.get('strength_score') or 0)
            score_text = f'{score:.1f}x от обычного уровня' if score > 0 else 'нет достаточной базы для сравнения'
            text = str(post.get('content_text') or 'Публикация без текстовой подписи').strip()[:500]
            blocks.append(
                f"Источник: {source}\n"
                f"Дата: {post.get('published_at') or 'не указана'}\n"
                f"Просмотры: {int(post.get('views') or 0)}; реакции: {int(post.get('reactions') or 0)}; "
                f"относительный сигнал: {score_text}\n"
                f"Ссылка: {post.get('post_url') or ''}\n"
                f"Текст: {text}"
            )
        return '\n\n---\n\n'.join(blocks)

    async def analyze_channel(self, user_id: int, posts: list[str]) -> str:
        profile, summary, examples = await self._context(user_id)
        material = '\n\n--- ПОСТ ---\n'.join(posts[:20])
        prompt = (
            f"{prompt_builder._compose_context(profile, summary, examples)}\n\n"
            "ЗАДАЧА: проанализируй последние публикации Telegram-канала как систему. "
            "Не выдумывай просмотры, подписчиков, ER и другие метрики, которых нет во входных данных. "
            "Сначала назови сильные стороны, затем повторяющиеся проблемы и практические улучшения.\n\n"
            f"Публикации:\n{material}\n\n"
            "Формат: сильные стороны; темы и рубрики; стиль и узнаваемость; структура и удержание; "
            "CTA; повторы/пробелы; 5 приоритетных действий на ближайшие 2 недели."
        )
        result = await self.openai_service.generate_text(prompt=prompt, system_prompt=SYSTEM_PROMPT_RU)
        await self.queries.add_generation_history(
            user_id,
            'channel_analysis',
            'channel_posts',
            material,
            result,
            {'posts_count': len(posts[:20]), 'provider': self.openai_service.last_provider},
        )
        return result
