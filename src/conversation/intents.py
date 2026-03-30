"""Phân loại intent từ tin nhắn text (lệnh /giaoviec, /vieccuatoi, …)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.conversation.validators import _normalize_slash_command_token


class Intent(str, Enum):
    """Các intent hội thoại được hỗ trợ."""

    ASSIGN_TASK = "ASSIGN_TASK"
    ASSIGN_TASK_SELF = "ASSIGN_TASK_SELF"
    MY_TASK = "MY_TASK"
    MARK_TASK_DONE = "MARK_TASK_DONE"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class IntentResult:
    """Kết quả router: intent + payload mở rộng (hiện dùng dict rỗng)."""

    intent: Intent
    payload: dict[str, str]


# Alias mặc định khi không có `templates.json`; có thể bị ghi đè bởi cấu hình JSON
DEFAULT_INTENT_ALIASES: dict[Intent, list[str]] = {
    Intent.ASSIGN_TASK: ["/giaoviec"],
    Intent.ASSIGN_TASK_SELF: ["/giaochotoi"],
    Intent.MY_TASK: ["/vieccuatoi"],
    Intent.MARK_TASK_DONE: ["/baoxong", "/baohoanthanh"],
    Intent.HELP: ["/huongdan", "/help"],
}


def _normalize_for_intent(message_text: str) -> str:
    """Chuẩn hoá text: trim + lower; với lệnh `/...` bỏ hậu tố `@bot` (nhóm Telegram)."""
    return _normalize_slash_command_token(message_text)


def _normalize_alias_map(intent_aliases: dict[str, list[str]] | None) -> dict[Intent, list[str]]:
    """Merge alias từ JSON với DEFAULT; key intent là tên enum string (ASSIGN_TASK, …)."""
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
    """So khớp chuỗi đã chuẩn hoá với từng alias; khớp đúng (equality) mới nhận intent."""
    normalized = _normalize_for_intent(message_text)
    aliases_map = _normalize_alias_map(intent_aliases)
    for intent, aliases in aliases_map.items():
        for alias in aliases:
            if normalized == alias:
                return IntentResult(intent=intent, payload={})
    return IntentResult(intent=Intent.UNKNOWN, payload={})
