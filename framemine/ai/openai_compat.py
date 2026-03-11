"""OpenAI-compatible AI backend using raw HTTP requests."""

import base64
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import requests

from .base import AIBackend

logger = logging.getLogger(__name__)


class OpenAICompatBackend(AIBackend):
    """AI backend for OpenAI and compatible APIs (e.g., local LLMs, Azure)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        delay_seconds: float = 1.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key or self._resolve_api_key()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries

    @staticmethod
    def _resolve_api_key() -> str:
        """Resolve from OPENAI_API_KEY env var."""
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable not set. "
                "Set it or pass api_key directly."
            )
        return key

    def extract(self, image_paths: list[Path], prompt: str) -> list[dict[str, Any]]:
        """Send images as base64 to OpenAI chat completions API."""
        if not image_paths:
            return []

        messages = self._build_messages(image_paths, prompt)
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return self.parse_response(text)
            except Exception as e:
                logger.warning(
                    "OpenAI request failed (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    str(e)[:120],
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay_seconds * (2**attempt))

        logger.error("Gave up after %d attempts", self.max_retries)
        return []

    @staticmethod
    def _encode_image(path: Path) -> str:
        """Base64-encode an image file."""
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    def _build_messages(
        self, image_paths: list[Path], prompt: str
    ) -> list[dict[str, Any]]:
        """Build OpenAI chat messages with base64 image_url content parts."""
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        for path in image_paths:
            mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
            b64 = self._encode_image(path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64}",
                    },
                }
            )

        return [{"role": "user", "content": content}]
