"""Abstract base class for AI backends."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import json
import re


class AIBackend(ABC):
    """Base class that all AI backends must implement."""

    @abstractmethod
    def extract(self, image_paths: list[Path], prompt: str) -> list[dict[str, Any]]:
        """Send images + prompt to AI, return parsed list of dicts."""

    @staticmethod
    def parse_response(text: str) -> list[dict[str, Any]]:
        """
        Parse AI response text into list of dicts.
        Handles: clean JSON, ```json fenced blocks, malformed responses.
        Returns empty list if parsing fails.
        """
        if not text or not text.strip():
            return []

        text = text.strip()

        # Try clean JSON first
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` fenced block
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fenced:
            try:
                result = json.loads(fenced.group(1).strip())
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                pass

        return []
