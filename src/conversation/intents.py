"""Intent router for Phase 3 conversation flow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    ASSIGN_TASK = "ASSIGN_TASK"
    MY_TASK = "MY_TASK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    payload: dict[str, str]


DEFAULT_INTENT_ALIASES: dict[Intent, list[str]] = {
    Intent.ASSIGN_TASK: ["/giaoviec"],
    Intent.MY_TASK: ["/vieccuatoi"],
}


def _normalize_for_intent(message_text: str) -> str:
    return message_text.strip().lower()


def _normalize_alias_map(intent_aliases: dict[str, list[str]] | None) -> dict[Intent, list[str]]:
    merged = {key: value[:] for key, value in DEFAULT_INTENT_ALIASES.items()}
    if not intent_aliases:
        return merged
    for key, aliases in intent_aliases.items():
        try:
            intent = Intent[str(key).strip().upper()]
        except KeyError:
            continue
        normalized_aliases = []
        for alias in aliases:
            value = _normalize_for_intent(str(alias))
            if value:
                normalized_aliases.append(value)
        if normalized_aliases:
            merged[intent] = normalized_aliases
    return merged


def resolve_intent(message_text: str, *, intent_aliases: dict[str, list[str]] | None = None) -> IntentResult:
    normalized = _normalize_for_intent(message_text)
    aliases_map = _normalize_alias_map(intent_aliases)
    for intent, aliases in aliases_map.items():
        for alias in aliases:
            if normalized == alias:
                return IntentResult(intent=intent, payload={})
    return IntentResult(intent=Intent.UNKNOWN, payload={})

