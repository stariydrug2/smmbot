from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class OpenAIService:
    """Сервис-обёртка над OpenAI Responses API.

    Отвечает за:
    - генерацию текста
    - генерацию текста по изображению
    - суммаризацию памяти бренда
    - анализ пользовательских примеров

    Важный момент: сервис не скрывает первичную причину ошибки.
    Он логирует исходное исключение и поднимает RuntimeError с понятным текстом,
    чтобы проблему можно было увидеть и в логах, и при желании отдать в бот.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Генерирует текст через Responses API."""
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=system_prompt or 'Ты полезный AI-ассистент.',
                input=prompt,
                temperature=temperature,
            )
            text = self._extract_output_text(response)
            if not text:
                raise RuntimeError('OpenAI вернул пустой ответ.')
            return text
        except Exception as exc:
            self._log_openai_exception('text_generation', exc, extra={'model': self.model})
            raise RuntimeError(self._humanize_exception(exc)) from exc

    async def generate_with_image(
        self,
        image_path: Path,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """Анализирует изображение и возвращает текстовый результат."""
        try:
            image_bytes = image_path.read_bytes()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            response = await self.client.responses.create(
                model=self.model,
                instructions=system_prompt or 'Ты полезный AI-ассистент.',
                input=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'input_text', 'text': prompt},
                            {'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{image_b64}'},
                        ],
                    }
                ],
            )
            text = self._extract_output_text(response)
            if not text:
                raise RuntimeError('OpenAI не вернул текст по изображению.')
            return text
        except Exception as exc:
            self._log_openai_exception(
                'vision_generation',
                exc,
                extra={'model': self.model, 'image_path': str(image_path)},
            )
            raise RuntimeError(self._humanize_exception(exc)) from exc

    async def generate_structured_content(self, prompt: str, system_prompt: str | None = None) -> str:
        """Генерация более структурированного результата с умеренной вариативностью."""
        return await self.generate_text(prompt=prompt, system_prompt=system_prompt, temperature=0.6)

    async def summarize_memory(self, raw_context: str) -> str:
        """Сжимает контекст бренда в короткую память для следующих генераций."""
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
        """Анализирует примеры постов и выделяет устойчивые стилевые признаки."""
        prompt = (
            'Проанализируй примеры постов пользователя и выдели стиль, ритм, лексику, '
            'подачу, структуру и повторы, которых стоит избегать.\n\n'
            + '\n\n'.join(examples)
        )
        return await self.generate_text(
            prompt=prompt,
            system_prompt='Ты редактор и бренд-стратег.',
            temperature=0.4,
        )

    @staticmethod
    def _extract_output_text(response: Any) -> str:
        """Надёжно извлекает итоговый текст из ответа SDK."""
        output_text = getattr(response, 'output_text', None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = getattr(response, 'output', None)
        if not output:
            return ''

        collected: list[str] = []
        for item in output:
            contents = getattr(item, 'content', None) or []
            for content in contents:
                text = getattr(content, 'text', None)
                if isinstance(text, str) and text.strip():
                    collected.append(text.strip())
        return '\n'.join(collected).strip()

    @staticmethod
    def _humanize_exception(exc: Exception) -> str:
        """Преобразует техническую ошибку в понятное сообщение для разработки/отладки."""
        if isinstance(exc, AuthenticationError):
            return 'Ошибка OpenAI: неверный API-ключ или нет доступа к проекту.'
        if isinstance(exc, PermissionDeniedError):
            return 'Ошибка OpenAI: у ключа нет доступа к этой модели или операции.'
        if isinstance(exc, NotFoundError):
            return 'Ошибка OpenAI: модель или ресурс не найдены. Проверь OPENAI_TEXT_MODEL.'
        if isinstance(exc, RateLimitError):
            return 'Ошибка OpenAI: превышен лимит запросов или закончилась квота.'
        if isinstance(exc, APITimeoutError):
            return 'Ошибка OpenAI: сервер слишком долго отвечал.'
        if isinstance(exc, APIConnectionError):
            return 'Ошибка OpenAI: не удалось подключиться к API.'
        if isinstance(exc, BadRequestError):
            return f'Ошибка OpenAI: некорректный запрос. {OpenAIService._extract_api_error_text(exc)}'
        if isinstance(exc, APIStatusError):
            return f'Ошибка OpenAI: API вернул статус {getattr(exc, "status_code", "unknown")}. {OpenAIService._extract_api_error_text(exc)}'
        if isinstance(exc, RuntimeError):
            return str(exc)
        return f'Ошибка OpenAI: {type(exc).__name__}: {str(exc)}'

    @staticmethod
    def _extract_api_error_text(exc: Exception) -> str:
        """Достаёт полезный текст из исключений OpenAI SDK, если он есть."""
        body = getattr(exc, 'body', None)
        if isinstance(body, dict):
            error = body.get('error')
            if isinstance(error, dict):
                message = error.get('message')
                code = error.get('code')
                type_ = error.get('type')
                parts = [str(part) for part in [message, f'code={code}' if code else None, f'type={type_}' if type_ else None] if part]
                if parts:
                    return ' '.join(parts)
        return str(exc)

    def _log_openai_exception(self, action: str, exc: Exception, extra: dict[str, Any] | None = None) -> None:
        """Подробно пишет ошибку в лог, чтобы не гадать вслепую."""
        payload = {
            'action': action,
            'model': self.model,
            'exception_type': type(exc).__name__,
            'message': str(exc),
        }
        if extra:
            payload.update(extra)

        status_code = getattr(exc, 'status_code', None)
        if status_code is not None:
            payload['status_code'] = status_code

        body = getattr(exc, 'body', None)
        if body is not None:
            payload['body'] = body

        logger.exception('OpenAI request failed | %s', payload)
