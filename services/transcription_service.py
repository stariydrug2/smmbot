from __future__ import annotations

import logging
from pathlib import Path

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


class TranscriptionService:
    """
    Транскрибация аудио через Polza.ai OpenAI-compatible endpoint.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=POLZA_BASE_URL)
        self.model = model

    async def transcribe(self, audio_path: Path) -> str:
        try:
            with audio_path.open("rb") as audio_file:
                response = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language="ru",
                )
            text = getattr(response, "text", "").strip()
            if not text:
                raise RuntimeError("Пустой результат транскрибации.")
            return text
        except Exception as exc:
            logger.exception(
                "Polza transcription failed: model=%s file=%s error=%s",
                self.model,
                audio_path,
                repr(exc),
            )
            raise RuntimeError(self._humanize_exception(exc)) from exc

    @staticmethod
    def _humanize_exception(exc: Exception) -> str:
        if isinstance(exc, AuthenticationError):
            return "Ошибка Polza.ai: неверный API-ключ или нет доступа к аккаунту."
        if isinstance(exc, PermissionDeniedError):
            return "Ошибка Polza.ai: доступ к транскрибации запрещён."
        if isinstance(exc, NotFoundError):
            return "Ошибка Polza.ai: модель транскрибации не найдена."
        if isinstance(exc, RateLimitError):
            return "Ошибка Polza.ai: превышен лимит запросов или закончился баланс."
        if isinstance(exc, APITimeoutError):
            return "Ошибка Polza.ai: сервер слишком долго отвечает."
        if isinstance(exc, APIConnectionError):
            return "Ошибка Polza.ai: не удалось подключиться к API."
        if isinstance(exc, BadRequestError):
            return f"Ошибка Polza.ai: неверный запрос на транскрибацию. Детали: {exc}"
        if isinstance(exc, UnprocessableEntityError):
            return f"Ошибка Polza.ai: аудио не удалось обработать. Детали: {exc}"
        if isinstance(exc, InternalServerError):
            return "Ошибка Polza.ai: внутренняя ошибка сервера транскрибации."
        return f"Ошибка Polza.ai: {type(exc).__name__}: {exc}"
