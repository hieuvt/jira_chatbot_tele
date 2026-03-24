"""Báo cáo định kỳ (Phase 5): phân loại quá hạn / sắp đến hạn, nhóm assignee, lọc theo users.json, render HTML Telegram."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import html as html_lib
from typing import Any

from telegram import Bot

from src.jira.models import JiraIssueRecord, QueryIssuesRequest
from src.storage.users_store import UsersStore


def _format_report_assignee_mention(*, telegram_id: str, record: dict[str, str] | None) -> str:
    """
    Chuỗi hiển thị sau 'Assignee: ' (sẽ html.escape khi gửi).
    Ưu tiên @user_name, rồi @telegram_display_name, rồi số telegram_id (không @).
    """
    dn = ""
    un = ""
    if record:
        dn = str(record.get("telegram_display_name", "")).strip()
        un = str(record.get("user_name", "")).strip()
    if un:
        body = un.lstrip("@").strip()
        return f"@{body}" if body else telegram_id
    if dn:
        body = dn.lstrip("@").strip()
        return f"@{body}" if body else telegram_id
    tid = str(telegram_id).strip()
    if tid.isdigit():
        return tid
    body = tid.lstrip("@").strip()
    return f"@{body}" if body else tid


@dataclass(frozen=True)
class ReportIssue:
    """Một dòng issue trong báo cáo (đã có due_date kiểu date)."""
    issue_key: str
    summary: str
    due_date: date


@dataclass
class AssigneeReport:
    """Một assignee (hoặc Unassigned): hai danh sách overdue / upcoming."""

    telegram_id: str | None  # None = nhóm Unassigned
    assignee_mention_text: str  # Chuỗi sau 'Assignee: ' (có thể có @)
    overdue: list[ReportIssue]
    upcoming: list[ReportIssue]


@dataclass
class ReportModel:
    """Mô hình báo cáo đầy đủ trước khi format chuỗi gửi Telegram."""

    today: date
    window_days: int
    total_upcoming: int
    total_overdue: int
    assignees: list[AssigneeReport]


class Reporter:
    """Gọi Jira client + đọc UsersStore, build tin nhắn HTML và gửi qua Bot API."""

    def __init__(
        self,
        *,
        jira_client: Any,
        users_store: UsersStore,
        project_key: str,
        bot_token: str,
        logger: Any | None = None,
    ) -> None:
        self.jira_client = jira_client
        self.users_store = users_store
        self.project_key = project_key
        self._bot = Bot(token=bot_token)
        self.logger = logger

    def build_report(self, *, window_days: int, now: datetime) -> ReportModel:
        """
        Dựng ReportModel theo contract Phase 5: quá hạn < today; sắp đến hạn trong [today, today+N].
        Assignee không có mapping Telegram bị bỏ (trừ Unassigned).
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware datetime")

        today = now.date()
        reverse_map = self.users_store.get_reverse_mapping()  # jira_id -> telegram_id

        query = QueryIssuesRequest(
            project_key=self.project_key,
            reporter_account_id="",  # Không lọc reporter trong JQL
            window_days=window_days,
            now=now,
        )
        grouped: dict[str, list[JiraIssueRecord]] = self.jira_client.query_issues_by_due_date_for_reporter(query)

        assignee_reports: list[AssigneeReport] = []
        for assignee_jira_id, records in grouped.items():
            assignee_key_norm = (assignee_jira_id or "").strip().lower()
            is_unassigned = (not assignee_jira_id) or assignee_key_norm == "unassigned"

            overdue_items: list[ReportIssue] = []
            upcoming_items: list[ReportIssue] = []

            for record in records:
                if not record.due_date:
                    continue
                try:
                    due = date.fromisoformat(record.due_date)
                except ValueError:
                    continue

                issue = ReportIssue(issue_key=record.issue_key, summary=record.summary, due_date=due)
                if due < today:
                    overdue_items.append(issue)
                else:
                    # Sắp đến hạn: khoảng đóng [today, today+N]
                    if due <= (today + timedelta(days=window_days)):
                        upcoming_items.append(issue)

            # Lọc theo mapping Telegram: Unassigned luôn hiện; assignee khác cần có trong reverse_map
            if not is_unassigned:
                telegram_id = reverse_map.get(str(assignee_jira_id).strip())
                if not telegram_id:
                    continue
                rec = self.users_store.get_user_record_by_telegram_id(telegram_id)
                mention_text = _format_report_assignee_mention(telegram_id=telegram_id, record=rec)
            else:
                telegram_id = None
                mention_text = "Unassigned"

            # Sắp issue: due_date tăng, rồi issue_key
            overdue_items.sort(key=lambda x: (x.due_date, x.issue_key))
            upcoming_items.sort(key=lambda x: (x.due_date, x.issue_key))

            if overdue_items or upcoming_items:
                assignee_reports.append(
                    AssigneeReport(
                        telegram_id=telegram_id,
                        assignee_mention_text=mention_text,
                        overdue=overdue_items,
                        upcoming=upcoming_items,
                    )
                )

        # Thứ tự assignee: telegram_id số tăng dần, Unassigned cuối
        def _assignee_sort_key(a: AssigneeReport) -> tuple[int, int, int]:
            if a.telegram_id is None:
                return (1, 0, 0)
            try:
                # Telegram id thường là số — sort số
                return (0, 0, int(a.telegram_id))
            except Exception:
                # Không parse int: xếp sau nhóm số
                return (0, 1, 0)

        assignee_reports.sort(key=_assignee_sort_key)

        total_upcoming = sum(len(a.upcoming) for a in assignee_reports)
        total_overdue = sum(len(a.overdue) for a in assignee_reports)

        return ReportModel(
            today=today,
            window_days=window_days,
            total_upcoming=total_upcoming,
            total_overdue=total_overdue,
            assignees=assignee_reports,
        )

    def build_report_messages(self, *, window_days: int, now: datetime) -> list[str]:
        """Chuyển ReportModel thành list tin nhắn (block 1 tổng + mỗi assignee một tin)."""
        model = self.build_report(window_days=window_days, now=now)

        # Khối 1: hai dòng tổng
        overall_text = f"Tổng sắp đến hạn: {model.total_upcoming}\nTổng quá hạn: {model.total_overdue}"

        messages: list[str] = [overall_text]

        jira_base_url = getattr(self.jira_client, "base_url", "") or ""
        jira_base_url = jira_base_url.rstrip("/")

        for assignee in model.assignees:
            escaped_assignee = html_lib.escape(assignee.assignee_mention_text)
            lines: list[str] = [f"Assignee: {escaped_assignee}"]

            if assignee.overdue:
                lines.append("Quá hạn:")
                for item in assignee.overdue:
                    escaped_issue = html_lib.escape(item.issue_key)
                    escaped_summary = html_lib.escape(item.summary)
                    if jira_base_url:
                        issue_url = f"{jira_base_url}/browse/{item.issue_key}"
                        issue_anchor = f'<a href="{html_lib.escape(issue_url, quote=True)}">{escaped_issue}</a>'
                        lines.append(
                            f"- {issue_anchor}: {escaped_summary} (due: {item.due_date.isoformat()})"
                        )
                    else:
                        lines.append(
                            f"- {escaped_issue}: {escaped_summary} (due: {item.due_date.isoformat()})"
                        )

            if assignee.upcoming:
                # Một dòng trống giữa Quá hạn và Sắp đến hạn khi cả hai đều có
                if assignee.overdue:
                    lines.append("")
                lines.append("Sắp đến hạn:")
                for item in assignee.upcoming:
                    escaped_issue = html_lib.escape(item.issue_key)
                    escaped_summary = html_lib.escape(item.summary)
                    if jira_base_url:
                        issue_url = f"{jira_base_url}/browse/{item.issue_key}"
                        issue_anchor = f'<a href="{html_lib.escape(issue_url, quote=True)}">{escaped_issue}</a>'
                        lines.append(
                            f"- {issue_anchor}: {escaped_summary} (due: {item.due_date.isoformat()})"
                        )
                    else:
                        lines.append(
                            f"- {escaped_issue}: {escaped_summary} (due: {item.due_date.isoformat()})"
                        )

            messages.append("\n".join(lines))

        return messages

    async def _send_messages_async(self, *, telegram_chat_id: int, message_texts: list[str]) -> None:
        """Gửi tuần tự từng tin với parse_mode HTML."""
        for idx, text in enumerate(message_texts):
            try:
                await self._bot.send_message(chat_id=telegram_chat_id, text=text, parse_mode="HTML")
            except Exception as exc:
                raise

    def send_report(self, *, telegram_chat_id: int, message_texts: list[str] | str) -> None:
        """
        API đồng bộ cho job scheduler: bọc asyncio.run để gọi Bot API async.
        """
        texts: list[str] = [message_texts] if isinstance(message_texts, str) else message_texts
        asyncio.run(self._send_messages_async(telegram_chat_id=telegram_chat_id, message_texts=texts))

    # Giữ chỗ tương thích cũ (chưa dùng)
    def get_due_tasks(self, window_days: int, now: datetime) -> dict[str, list[dict[str, str]]]:
        _ = (window_days, now)
        return {}

    def render_report(self, issues: dict[str, list[dict[str, str]]]) -> str:
        _ = issues
        return "Báo cáo định kỳ (unimplemented legacy renderer)"

