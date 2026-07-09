from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)


class ImageService:
    """Image generation service for Polza.ai Media API.

    Uses the model-specific Media API because Polza's GPT Image 1.5 guide
    requires `aspect_ratio` and `quality` in `input`, and returns a media task id
    that should be polled via GET /v1/media/{id}.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = "https://polza.ai/api/v1"

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        *,
        aspect_ratio: str = "1:1",
        quality: str = "medium",
        reference_images: Iterable[Path] | None = None,
    ) -> Path:
        payload = {
            "model": self.model,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "images": self._encode_images(reference_images or []),
            },
            "async": True,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/media", headers=headers, json=payload)
            if response.status_code >= 400:
                detail = self._safe_detail(response)
                logger.error("Polza.ai image request failed: %s | %s", response.status_code, detail)
                raise RuntimeError(
                    "Ошибка Polza.ai при генерации изображения: "
                    f"HTTP {response.status_code}. {detail}"
                )

            data = response.json()
            task_id = data.get("id")
            if not task_id:
                logger.error("Polza.ai image response without id: %s", data)
                raise RuntimeError("Polza.ai не вернул id задачи генерации изображения.")

            result = await self._poll_media_status(client, headers, task_id)
            image_url = self._extract_image_url(result)
            if not image_url:
                logger.error("Polza.ai completed without image url: %s", result)
                raise RuntimeError("Polza.ai завершил задачу без ссылки на изображение.")

            file_response = await client.get(image_url)
            file_response.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(file_response.content)
            return output_path

    async def _poll_media_status(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        task_id: str,
        *,
        max_attempts: int = 60,
        delay_seconds: float = 3.0,
    ) -> dict:
        for _ in range(max_attempts):
            response = await client.get(f"{self.base_url}/media/{task_id}", headers=headers)
            if response.status_code >= 400:
                detail = self._safe_detail(response)
                logger.error("Polza.ai media status failed: %s | %s", response.status_code, detail)
                raise RuntimeError(
                    "Ошибка Polza.ai при проверке статуса изображения: "
                    f"HTTP {response.status_code}. {detail}"
                )

            data = response.json()
            status = data.get("status")
            if status == "completed":
                return data
            if status == "failed":
                error = data.get("error") or {}
                message = error.get("message") or "Неизвестная ошибка генерации"
                code = error.get("code") or "UNKNOWN"
                raise RuntimeError(f"Polza.ai не смог сгенерировать изображение: {code}: {message}")
            if status in {"pending", "processing"}:
                await asyncio.sleep(delay_seconds)
                continue
            raise RuntimeError(f"Неожиданный статус генерации изображения: {status!r}")

        raise RuntimeError("Истекло время ожидания генерации изображения в Polza.ai.")

    @staticmethod
    def _extract_image_url(data: dict) -> str | None:
        media = data.get("data")
        if isinstance(media, dict):
            if media.get("url"):
                return str(media["url"])
            if isinstance(media.get("images"), list) and media["images"]:
                first = media["images"][0]
                if isinstance(first, dict) and first.get("url"):
                    return str(first["url"])
        if isinstance(media, list) and media:
            first = media[0]
            if isinstance(first, dict) and first.get("url"):
                return str(first["url"])
        return None

    @staticmethod
    def _safe_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return response.text.strip()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                if code or message:
                    return f"{code or 'ERROR'}: {message or 'Без описания'}"
            message = data.get("message")
            if message:
                return str(message)
        return str(data)

    @staticmethod
    def _encode_images(paths: Iterable[Path]) -> list[dict[str, str]]:
        encoded: list[dict[str, str]] = []
        for path in paths:
            suffix = path.suffix.lower().lstrip(".") or "png"
            mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
            raw = base64.b64encode(path.read_bytes()).decode("utf-8")
            encoded.append({
                "type": "base64",
                "data": f"data:image/{mime};base64,{raw}",
            })
        return encoded
