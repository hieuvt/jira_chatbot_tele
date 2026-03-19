"""Periodic report stub."""

from datetime import datetime


class Reporter:
    def get_due_tasks(self, window_days: int, now: datetime) -> dict[str, list[dict[str, str]]]:
        _ = (window_days, now)
        return {}

    def render_report(self, issues: dict[str, list[dict[str, str]]]) -> str:
        _ = issues
        return "Báo cáo định kỳ (skeleton)"

    def send_report(self, telegram_chat_id: int, message_text: str) -> None:
        _ = (telegram_chat_id, message_text)

