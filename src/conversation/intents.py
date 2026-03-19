"""Intent routing without LLM."""

from enum import Enum


class Intent(str, Enum):
    GIAO_VIEC = "giao_viec"
    VIEC_CUA_TOI = "viec_cua_toi"
    HELP = "help"
    UNKNOWN = "unknown"


def resolve_intent(message_text: str) -> Intent:
    normalized = message_text.strip().lower()
    if normalized == "giao việc":
        return Intent.GIAO_VIEC
    if normalized == "việc của tôi":
        return Intent.VIEC_CUA_TOI
    if normalized in {"help", "/help"}:
        return Intent.HELP
    return Intent.UNKNOWN

