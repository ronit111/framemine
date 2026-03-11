"""Title normalization and deduplication."""

import re
import logging

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """Normalize: lowercase, strip, remove non-alphanumeric (keep spaces), collapse whitespace."""
    t = title.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t


def deduplicate(items: list[dict], key_fields: list[str] | None = None) -> list[dict]:
    """
    Remove duplicates based on normalized key fields.

    key_fields defaults to ["title"]. Multiple fields joined with "|".
    Preserves first occurrence order. Logs removal count.
    """
    if key_fields is None:
        key_fields = ["title"]

    seen: set[str] = set()
    unique: list[dict] = []

    for item in items:
        parts = []
        for field in key_fields:
            value = item.get(field, "") or ""
            parts.append(normalize_title(str(value)))
        key = "|".join(parts)

        if key not in seen:
            seen.add(key)
            unique.append(item)

    removed = len(items) - len(unique)
    if removed > 0:
        logger.info("Deduplication removed %d duplicate(s) from %d items", removed, len(items))

    return unique
