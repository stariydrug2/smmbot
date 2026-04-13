from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

POLZA_V1_BASE_URL = "https://polza.ai/api/v1"
POLZA_V2_IMAGES_URL = "https://polza.ai/api/v2/images/generations"


class ImageService:
    """
    Генерация изображений через Polza.ai.

    Используем прямой HTTP-запрос вместо OpenAI SDK ради более предсказуемой
    обработки Polza-ответов:
    - sync-ответ с готовым b64/url
    - pending-ответ с последующим polling через GET /v1/media/{id}
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def generate_image(self, prompt: str, output_path: Path) -> Path:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "high",
            "response_format": "b64_json",
            "output_format": "png",
        }

        async with httpx.AsyncClient(timeout=130.0) as client:
            try:
                response = await client.post(POLZA_V2_IMAGES_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                logger.exception("Polza image generation HTTP error: %s", exc.response.text)
                raise RuntimeError(
                    f"Ошибка Polza.ai при генерации изображения: HTTP {exc.response.status_code}."
                ) from exc
            except Exception as exc:
                logger.exception("Polza image generation failed")
                raise RuntimeError(f"Ошибка Polza.ai при генерации изображения: {exc}") from exc

            output_path.parent.mkdir(parents=True, exist_ok=True)

            if self._has_ready_image(data):
                return await self._save_result(data, output_path, client)

            task_id = data.get("id")
            status = data.get("status")
            if task_id and status in {"pending", "processing"}:
                return await self._poll_until_ready(task_id=task_id, output_path=output_path, client=client)

            error_message = self._extract_error_message(data) or "Неизвестный ответ API."
            raise RuntimeError(f"Polza.ai не вернул изображение. {error_message}")

    async def _poll_until_ready(self, task_id: str, output_path: Path, client: httpx.AsyncClient) -> Path:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        status_url = f"{POLZA_V1_BASE_URL}/media/{task_id}"

        for _ in range(60):
            await asyncio.sleep(3)
            response = await client.get(status_url, headers=headers)
            response.raise_for_status()
            data = response.json()

            status = data.get("status")
            if status == "completed" and self._has_ready_image(data):
                return await self._save_result(data, output_path, client)
            if status == "failed":
                error_message = self._extract_error_message(data) or "Генерация завершилась ошибкой."
                raise RuntimeError(f"Polza.ai не смог сгенерировать изображение. {error_message}")

        raise RuntimeError("Polza.ai не успел завершить генерацию изображения вовремя.")

    @staticmethod
    def _has_ready_image(data: dict[str, Any]) -> bool:
        items = data.get("data")
        return isinstance(items, list) and len(items) > 0 and isinstance(items[0], dict)

    async def _save_result(self, data: dict[str, Any], output_path: Path, client: httpx.AsyncClient) -> Path:
        item = data["data"][0]

        b64_json = item.get("b64_json")
        if b64_json:
            output_path.write_bytes(base64.b64decode(b64_json))
            return output_path

        url = item.get("url")
        if url:
            file_response = await client.get(url, timeout=130.0)
            file_response.raise_for_status()
            output_path.write_bytes(file_response.content)
            return output_path

        raise RuntimeError("Polza.ai вернул ответ без изображения.")

    @staticmethod
    def _extract_error_message(data: dict[str, Any]) -> str:
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "")
        if isinstance(error, str):
            return error
        return ""
