from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

logger = logging.getLogger(__name__)

POLZA_BASE_URL = "https://polza.ai/api/v1"


class OpenAIService:
    """
    Текстовый и vision-сервис поверх Polza.ai через OpenAI-compatible Chat Completions API.

    Важный нюанс:
    - Для текстовой генерации здесь используется chat.completions.create(...)
      вместо Responses API, потому что в документации Polza Responses API отмечен
      как beta, а Chat Completions — основной совместимый путь.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=POLZA_BASE_URL)
        self.model = model

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt or "Ты полезный AI-ассистент.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=temperature,
            )
            content = completion.choices[0].message.content
            text = self._extract_text_content(content)
            if not text:
                raise RuntimeError("Модель вернула пустой ответ.")
            return text.strip()
        except Exception as exc:
            logger.exception(
                "Polza text generation failed: model=%s error=%s",
                self.model,
                repr(exc),
            )
            raise RuntimeError(self._humanize_exception(exc)) from exc

    async def generate_with_image(
        self,
        image_path: Path,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """
        Анализирует изображение через текстовую модель по OpenAI-compatible
        multimodal chat format.
        """
        try:
            mime_type = self._guess_mime_type(image_path)
            image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
            data_url = f"data:{mime_type};base64,{image_b64}"

            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt or "Ты полезный AI-ассистент.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    },
                ],
                temperature=0.4,
            )
            content = completion.choices[0].message.content
            text = self._extract_text_content(content)
            if not text:
                raise RuntimeError("Модель не вернула текст по изображению.")
            return text.strip()
        except Exception as exc:
            logger.exception(
                "Polza vision request failed: model=%s file=%s error=%s",
                self.model,
                image_path,
                repr(exc),
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
            temperature=0.6,
        )

    async def summarize_memory(self, raw_context: str) -> str:
        prompt = (
            "Сожми контекст бренда в короткую полезную память для будущих генераций. "
            "Оставь только важное: позиционирование, ЦА, тон, запреты, форматы, "
            "сильные акценты.\n\n"
            f"Контекст:\n{raw_context}"
        )
        return await self.generate_text(
            prompt=prompt,
            system_prompt="Ты сильный редактор бренд-памяти.",
            temperature=0.3,
        )

    async def analyze_examples(self, examples: list[str]) -> str:
        prompt = (
            "Проанализируй примеры постов пользователя и выдели стиль, ритм, лексику, "
            "подачу, структуру и повторы, которых стоит избегать.\n\n"
            + "\n\n".join(examples)
        )
        return await self.generate_text(
            prompt=prompt,
            system_prompt="Ты редактор и бренд-стратег.",
            temperature=0.4,
        )

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """
        Нормализует content в строку.
        OpenAI-compatible провайдеры обычно возвращают строку, но на всякий случай
        поддерживаем и список блоков.
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                    continue
                text_attr = getattr(item, "text", None)
                if text_attr:
                    parts.append(str(text_attr))
            return "\n".join(part.strip() for part in parts if part and str(part).strip())

        return str(content)

    @staticmethod
    def _guess_mime_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _humanize_exception(exc: Exception) -> str:
        if isinstance(exc, AuthenticationError):
            return "Ошибка Polza.ai: неверный API-ключ или нет доступа к аккаунту."
        if isinstance(exc, PermissionDeniedError):
            return "Ошибка Polza.ai: доступ к этой модели или операции запрещён."
        if isinstance(exc, NotFoundError):
            return "Ошибка Polza.ai: модель или endpoint не найдены."
        if isinstance(exc, RateLimitError):
            return "Ошибка Polza.ai: превышен лимит запросов или закончился баланс."
        if isinstance(exc, APITimeoutError):
            return "Ошибка Polza.ai: сервер слишком долго отвечает. Попробуйте ещё раз."
        if isinstance(exc, APIConnectionError):
            return "Ошибка Polza.ai: не удалось подключиться к API."
        if isinstance(exc, BadRequestError):
            return f"Ошибка Polza.ai: неверный запрос. Детали: {exc}"
        if isinstance(exc, UnprocessableEntityError):
            return f"Ошибка Polza.ai: запрос не удалось обработать. Детали: {exc}"
        if isinstance(exc, InternalServerError):
            return "Ошибка Polza.ai: внутренняя ошибка сервера."
        return f"Ошибка Polza.ai: {type(exc).__name__}: {exc}"
