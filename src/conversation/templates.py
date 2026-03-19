"""Load fixed response templates from external JSON file."""

from __future__ import annotations

import json
from pathlib import Path


def load_templates(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("templates.json must be an object of fixed keys.")
    return {str(k): str(v) for k, v in data.items()}

