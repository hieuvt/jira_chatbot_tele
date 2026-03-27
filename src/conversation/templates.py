"""Đọc `templates.json`: câu trả lời bot (`TPL_*`) và alias intent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TemplateBundle:
    """Gói template đã parse: bot_replies + intent_aliases (string keys cho state machine)."""

    bot_replies: dict[str, str]
    intent_aliases: dict[str, list[str]] = field(default_factory=dict)


# Fallback khi file JSON không có user_inputs (schema phẳng cũ)
DEFAULT_INTENT_ALIASES: dict[str, list[str]] = {
    "ASSIGN_TASK": ["giao việc", "/giao việc", "/giaoviec", "@bot giao việc"],
    "ASSIGN_TASK_SELF": ["/giaochotoi", "giao cho tôi", "/giao cho tôi", "@bot giao cho tôi"],
    "MY_TASK": ["/vieccuatoi", "việc của tôi", "/việc của tôi", "@bot việc của tôi"],
}


def load_template_bundle(path: Path) -> TemplateBundle:
    """Load JSON; hỗ trợ schema mới (bot_replies + user_inputs) hoặc phẳng chỉ TPL_*."""
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("templates.json must be an object.")

    # Tương thích file cũ: toàn key TPL_* ở root
    if "bot_replies" not in data and any(str(k).startswith("TPL_") for k in data.keys()):
        bot_replies = {str(k): str(v) for k, v in data.items()}
        return TemplateBundle(bot_replies=bot_replies, intent_aliases=DEFAULT_INTENT_ALIASES.copy())

    bot_replies_obj = data.get("bot_replies")
    if not isinstance(bot_replies_obj, dict):
        raise ValueError("templates.json.bot_replies must be an object.")
    bot_replies = {str(k): str(v) for k, v in bot_replies_obj.items()}

    user_inputs = data.get("user_inputs", {})
    if user_inputs is None:
        user_inputs = {}
    if not isinstance(user_inputs, dict):
        raise ValueError("templates.json.user_inputs must be an object.")
    intent_aliases_obj = user_inputs.get("intent_aliases", {})
    if intent_aliases_obj is None:
        intent_aliases_obj = {}
    if not isinstance(intent_aliases_obj, dict):
        raise ValueError("templates.json.user_inputs.intent_aliases must be an object.")

    intent_aliases: dict[str, list[str]] = {}
    for intent_name, aliases in intent_aliases_obj.items():
        if not isinstance(aliases, list):
            raise ValueError(f"Intent aliases for '{intent_name}' must be an array.")
        alias_values = [str(item).strip() for item in aliases if str(item).strip()]
        intent_aliases[str(intent_name)] = alias_values

    merged_aliases = DEFAULT_INTENT_ALIASES.copy()
    merged_aliases.update(intent_aliases)
    return TemplateBundle(bot_replies=bot_replies, intent_aliases=merged_aliases)


def load_templates(path: Path) -> dict[str, str]:
    """Chỉ lấy map TPL -> chuỗi (tiện cho code cũ)."""
    return load_template_bundle(path).bot_replies
