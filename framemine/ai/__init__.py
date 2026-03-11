"""AI backend factory."""

from .base import AIBackend
from .gemini import GeminiBackend
from .openai_compat import OpenAICompatBackend


def create_backend(config: dict) -> AIBackend:
    """
    Factory function. Creates the appropriate backend from config dict.

    config = {
        "backend": "gemini",  # or "openai"
        "gemini": { ... },
        "openai": { ... },
    }
    """
    backend_name = config.get("backend", "gemini")
    if backend_name == "gemini":
        gemini_cfg = config.get("gemini", {})
        return GeminiBackend(
            api_key=gemini_cfg.get("api_key"),
            models=gemini_cfg.get("models"),
            delay_seconds=gemini_cfg.get("delay_seconds", 4.0),
            max_retries_per_model=gemini_cfg.get("max_retries_per_model", 3),
        )
    elif backend_name == "openai":
        openai_cfg = config.get("openai", {})
        return OpenAICompatBackend(
            api_key=openai_cfg.get("api_key"),
            base_url=openai_cfg.get("base_url", "https://api.openai.com/v1"),
            model=openai_cfg.get("model", "gpt-4o-mini"),
            delay_seconds=openai_cfg.get("delay_seconds", 1.0),
            max_retries=openai_cfg.get("max_retries", 3),
        )
    else:
        raise ValueError(f"Unknown AI backend: {backend_name}")
