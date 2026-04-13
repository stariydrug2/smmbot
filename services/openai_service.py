from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Iterable

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class OpenAIService:
    """
    Compatibility layer that preserves the existing service name and method
    signatures, but routes text/vision generation through the Gemini API.

    This lets the rest of the bot keep working without changes to handlers,
    content services, or dependency injection.
    """

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or not api_key.strip():
            raise ValueError('Gemini API key is empty. Set OPENAI_API_KEY to your Google AI Studio key.')
        if not model or not model.strip():
            raise ValueError('Gemini model is empty. Set OPENAI_TEXT_MODEL, for example: gemini-2.5-flash')

        self.client = genai.Client(api_key=api_key)
        self.model = model.strip()

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Generate plain text with Gemini."""
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                ),
            )
            return self._extract_text(response)
        except Exception as exc:
            logger.exception(
                'Gemini text generation failed | model=%s | error_type=%s | error=%s',
                self.model,
                type(exc).__name__,
                str(exc),
            )
            raise RuntimeError(self._humanize_exception(exc)) from exc

    async def generate_with_image(
        self,
        image_path: Path,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.4,
    ) -> str:
        """Analyze an image and return text with Gemini multimodal input."""
        try:
            mime_type = self._guess_mime_type(image_path)
            image_bytes = image_path.read_bytes()
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                ),
            )
            return self._extract_text(response)
        except Exception as exc:
            logger.exception(
                'Gemini image analysis failed | model=%s | file=%s | error_type=%s | error=%s',
                self.model,
                image_path,
                type(exc).__name__,
                str(exc),
            )
            raise RuntimeError(self._humanize_exception(exc)) from exc

    async def generate_structured_content(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        return await self.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.5,
        )

    async def summarize_memory(self, raw_context: str) -> str:
        prompt = (
            'Сожми контекст бренда в короткую полезную память для будущих генераций. '
            'Оставь только важное: позиционирование, ЦА, тон, запреты, форматы, сильные акценты.\n\n'
            f'Контекст:\n{raw_context}'
        )
        return await self.generate_text(
            prompt=prompt,
            system_prompt='Ты сильный редактор бренд-памяти.',
            temperature=0.3,
        )

    async def analyze_examples(self, examples: list[str]) -> str:
        prompt = (
            'Проанализируй примеры постов пользователя и выдели стиль, ритм, лексику, подачу, '
            'структуру и повторы, которых стоит избегать.\n\n'
            + '\n\n'.join(examples)
        )
        return await self.generate_text(
            prompt=prompt,
            system_prompt='Ты редактор и бренд-стратег.',
            temperature=0.4,
        )

    def _extract_text(self, response: object) -> str:
        """Safely extract model text from a Gemini response."""
        text = getattr(response, 'text', None)
        if text and str(text).strip():
            return str(text).strip()

        candidates = getattr(response, 'candidates', None) or []
        collected: list[str] = []

        for candidate in candidates:
            content = getattr(candidate, 'content', None)
            parts = getattr(content, 'parts', None) or []
            for part in parts:
                part_text = getattr(part, 'text', None)
                if part_text and str(part_text).strip():
                    collected.append(str(part_text).strip())

        if collected:
            return '\n'.join(collected).strip()

        raise RuntimeError('Gemini не вернул текст. Возможна блокировка safety-фильтром или пустой ответ.')

    def _guess_mime_type(self, image_path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(str(image_path))
        return mime_type or 'image/jpeg'

    def _humanize_exception(self, exc: Exception) -> str:
        raw = str(exc).lower()

        if 'api key' in raw or 'api_key' in raw or 'permission denied' in raw or 'unauthenticated' in raw or '401' in raw:
            return 'Ошибка Gemini: неверный API-ключ или нет доступа к Gemini API.'
        if 'quota' in raw or '429' in raw or 'rate limit' in raw or 'resource has been exhausted' in raw:
            return 'Ошибка Gemini: превышена квота или лимит запросов.'
        if 'not found' in raw or 'model' in raw and 'not' in raw:
            return 'Ошибка Gemini: модель не найдена. Проверь OPENAI_TEXT_MODEL, например gemini-2.5-flash.'
        if 'safety' in raw or 'blocked' in raw:
            return 'Gemini заблокировал ответ из-за safety-настроек или содержания запроса.'
        return f'Ошибка Gemini: {type(exc).__name__}: {exc}'
