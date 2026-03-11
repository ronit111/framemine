"""Schema loading and management for framemine extraction schemas."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMAS_DIR = Path(__file__).parent / "schemas"

REQUIRED_FIELDS = {"name", "display_name", "description", "prompt", "output_columns", "dedup_key"}


@dataclass
class Schema:
    name: str                          # e.g., "books"
    display_name: str                  # e.g., "Books & Reading"
    description: str                   # One-line description
    prompt: str                        # Full extraction prompt for the AI
    output_columns: list[str]          # Ordered column names for Excel output
    dedup_key: list[str]               # Fields to use for deduplication (e.g., ["title"])
    enrichment: str | None = None      # Enrichment type: "books" or None
    item_type_field: str | None = None # Field name that indicates item type (e.g., "type")


def list_schemas() -> list[str]:
    """Return sorted list of available schema names (YAML filenames without extension)."""
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.yaml"))


def load_schema(name: str) -> Schema:
    """
    Load a schema by name from the schemas directory.

    Raises FileNotFoundError if schema doesn't exist.
    Raises ValueError if YAML is malformed or missing required fields.
    """
    path = SCHEMAS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Schema '{name}' not found at {path}")

    with open(path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Malformed YAML in schema '{name}': {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Schema '{name}' must be a YAML mapping, got {type(data).__name__}")

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Schema '{name}' missing required fields: {', '.join(sorted(missing))}")

    # Validate types
    if not isinstance(data["output_columns"], list) or not data["output_columns"]:
        raise ValueError(f"Schema '{name}': output_columns must be a non-empty list")
    if not isinstance(data["dedup_key"], list) or not data["dedup_key"]:
        raise ValueError(f"Schema '{name}': dedup_key must be a non-empty list")
    if not isinstance(data["prompt"], str) or not data["prompt"].strip():
        raise ValueError(f"Schema '{name}': prompt must be a non-empty string")

    return Schema(
        name=data["name"],
        display_name=data["display_name"],
        description=data["description"],
        prompt=data["prompt"],
        output_columns=data["output_columns"],
        dedup_key=data["dedup_key"],
        enrichment=data.get("enrichment"),
        item_type_field=data.get("item_type_field"),
    )


def get_schema_info() -> list[dict[str, str]]:
    """Return list of {name, display_name, description} for all schemas. For the 'schemas' CLI command."""
    result = []
    for name in list_schemas():
        schema = load_schema(name)
        result.append({
            "name": schema.name,
            "display_name": schema.display_name,
            "description": schema.description,
        })
    return result
