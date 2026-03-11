"""Gemini AI backend with model rotation for rate-limit resilience."""

import logging
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image

from .base import AIBackend

logger = logging.getLogger(__name__)

DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


class ModelRotator:
    """Rotate through Gemini models to avoid per-model rate limits."""

    def __init__(self, models: list[str]):
        self.models = list(models)
        self.current_idx = 0
        self.exhausted: set[str] = set()

    @property
    def current(self) -> str:
        return self.models[self.current_idx]

    def rotate(self) -> bool:
        """Switch to next non-exhausted model. Returns False if all exhausted."""
        self.exhausted.add(self.current)
        for i in range(len(self.models)):
            idx = (self.current_idx + 1 + i) % len(self.models)
            if self.models[idx] not in self.exhausted:
                self.current_idx = idx
                logger.info("Rotated to model %s", self.current)
                return True
        return False

    def reset(self) -> None:
        """Clear exhausted set so all models are available again."""
        self.exhausted.clear()


class GeminiBackend(AIBackend):
    """AI backend using Google Gemini with model rotation on rate limits."""

    def __init__(
        self,
        api_key: str | None = None,
        models: list[str] | None = None,
        delay_seconds: float = 4.0,
        max_retries_per_model: int = 3,
    ):
        self.api_key = api_key or self._resolve_api_key()
        self.models = models or list(DEFAULT_MODELS)
        self.delay_seconds = delay_seconds
        self.max_retries_per_model = max_retries_per_model
        self._rotator = ModelRotator(self.models)

    @staticmethod
    def _resolve_api_key() -> str:
        """Resolve from GEMINI_API_KEY env var. Raises RuntimeError if not found."""
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable not set. "
                "Set it or pass api_key directly."
            )
        return key

    def extract(self, image_paths: list[Path], prompt: str) -> list[dict[str, Any]]:
        """Send images to Gemini with model rotation on 429 errors."""
        from google import genai

        if not image_paths:
            return []

        # Load images
        images = []
        for p in image_paths:
            try:
                images.append(Image.open(p))
            except Exception:
                logger.warning("Failed to open image: %s", p)
                continue

        if not images:
            return []

        client = genai.Client(api_key=self.api_key)
        total_attempts = self.max_retries_per_model * len(self.models)

        for attempt in range(total_attempts):
            try:
                response = client.models.generate_content(
                    model=self._rotator.current,
                    contents=[prompt] + images,
                )
                text = response.text.strip()
                return self.parse_response(text)

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    if self._rotator.rotate():
                        time.sleep(2)
                        continue
                    # All models exhausted -- backoff and reset
                    wait = self.delay_seconds * (
                        2 ** min(attempt // len(self.models), 3)
                    )
                    logger.warning(
                        "All models exhausted, waiting %.0fs before reset", wait
                    )
                    time.sleep(wait)
                    self._rotator.reset()
                else:
                    logger.error("Gemini error: %s", err_str[:120])
                    return []

        logger.error(
            "Gave up after %d attempts across all models", total_attempts
        )
        return []
