from __future__ import annotations

import base64
import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_text(self, prompt: str, system_prompt: str | None = None, temperature: float = 0.7) -> str:
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {'role': 'system', 'content': system_prompt or 'Ты полезный AI-ассистент.'},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=temperature,
            )
            return response.output_text.strip()
        except Exception as exc:
            logger.exception('OpenAI text generation failed')
            raise RuntimeError('Не удалось получить ответ от модели.') from exc

    async def generate_with_image(self, image_path: Path, prompt: str, system_prompt: str | None = None) -> str:
        try:
            image_b64 = base64.b64encode(image_path.read_bytes()).decode('utf-8')
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {
                        'role': 'system',
                        'content': [{'type': 'input_text', 'text': system_prompt or 'Ты полезный AI-ассистент.'}],
                    },
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'input_text', 'text': prompt},
                            {'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{image_b64}'},
                        ],
                    },
                ],
            )
            return response.output_text.strip()
        except Exception as exc:
            logger.exception('OpenAI vision generation failed')
            raise RuntimeError('Не удалось обработать изображение.') from exc

    async def generate_structured_content(self, prompt: str, system_prompt: str | None = None) -> str:
        return await self.generate_text(prompt=prompt, system_prompt=system_prompt, temperature=0.6)

    async def summarize_memory(self, raw_context: str) -> str:
        prompt = (
            'Сожми контекст бренда в короткую полезную память для будущих генераций. '
            'Оставь только важное: позиционирование, ЦА, тон, запреты, форматы, сильные акценты.\n\n'
            f'Контекст:\n{raw_context}'
        )
        return await self.generate_text(prompt=prompt, system_prompt='Ты сильный редактор бренд-памяти.', temperature=0.3)

    async def analyze_examples(self, examples: list[str]) -> str:
        prompt = (
            'Проанализируй примеры постов пользователя и выдели стиль, ритм, лексику, подачу, структуру и повторы, которых стоит избегать.\n\n'
            + '\n\n'.join(examples)
        )
        return await self.generate_text(prompt=prompt, system_prompt='Ты редактор и бренд-стратег.', temperature=0.4)
