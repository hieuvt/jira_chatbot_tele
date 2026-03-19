"""Conversation state container (in-memory, per chat+user)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


STATE_TIMEOUT_MINUTES = 15


@dataclass
class ConversationBuffer:
    summary: str | None = None
    description: str | None = None
    checklist_items: list[str] = field(default_factory=list)
    due_days: int | None = None
    attachments: list[dict[str, object]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


def is_expired(buffer: ConversationBuffer, now: datetime | None = None) -> bool:
    point = now or datetime.now(timezone.utc)
    return point - buffer.updated_at > timedelta(minutes=STATE_TIMEOUT_MINUTES)

