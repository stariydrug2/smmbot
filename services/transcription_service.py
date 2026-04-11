from __future__ import annotations

import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(self, audio_path: Path) -> str:
        try:
            with audio_path.open('rb') as audio_file:
                response = await self.client.audio.transcriptions.create(model=self.model, file=audio_file)
            text = getattr(response, 'text', '').strip()
            if not text:
                raise RuntimeError('Пустой результат транскрибации.')
            return text
        except Exception as exc:
            logger.exception('Transcription failed')
            raise RuntimeError('Не удалось распознать аудио.') from exc
