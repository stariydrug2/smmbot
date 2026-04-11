from __future__ import annotations

import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class ImageService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_image(self, prompt: str, output_path: Path) -> Path:
        try:
            result = await self.client.images.generate(model=self.model, prompt=prompt, size='1024x1024')
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(base64.b64decode(result.data[0].b64_json))
            return output_path
        except Exception as exc:
            logger.exception('Image generation failed')
            raise RuntimeError('Не удалось сгенерировать изображение.') from exc
