"""Báo cáo định kỳ (Phase 5): phân loại quá hạn / sắp đến hạn, nhóm assignee, lọc theo users.json, render HTML Telegram."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import html as html_lib
from typing import Any

from telegram import Bot

from src.jira.models import JiraIssueRecord, QueryIssuesRequest, QueryRecentlyCompletedRequest
from src.storage.users_store import UsersStore


def _format_report_assignee_mention(*, telegram_username: str, record: dict[str, str] | None) -> str:
    """
    Chuỗi hiển thị sau 'Assignee: ' (sẽ html.escape khi gửi).
    Ưu tiên @user_name (username trong store), rồi @telegram_display_name, cuối cùng username_key thô (không @).
    """
    dn = ""
    un = ""
    if record:
        dn = str(record.get("telegram_display_name", "")).strip()
        un = str(record.get("user_name", "")).strip()
    if un:
        body = un.lstrip("@").strip()
        return f"@{body}" if body else telegram_username
    if dn:
        body = dn.lstrip("@").strip()
        return f"@{body}" if body else telegram_username
    return str(telegram_username).strip() or "Unknown"


@dataclass(frozen=True)
class ReportIssue:
    """Một dòng issue trong báo cáo; due_date None khi Jira không có duedate."""
    issue_key: str
    summary: str
    due_date: date | None


@dataclass
class AssigneeReport:
    """Một assignee (hoặc Unassigned): quá hạn / sắp đến hạn / hoàn thành gần đây."""

    telegram_username: str | None  # None = nhóm Unassigned; lowercase @username khớp users.json
    assignee_mention_text: str  # Chuỗi sau 'Assignee: ' (có thể có @)
    overdue: list[ReportIssue]
    upcoming: list[ReportIssue]
    completed_recent: list[ReportIssue]


@dataclass
class ReportModel:
    """Mô hình báo cáo đầy đủ trước khi format chuỗi gửi Telegram."""

    today: date
    window_days: int
    total_upcoming: int
    total_overdue: int
    total_completed_24h: int
    assignees: list[AssigneeReport]


def _format_report_issue_line(*, item: ReportIssue, jira_base_url: str) -> str:
    escaped_issue = html_lib.escape(item.issue_key)
    escaped_summary = html_lib.escape(item.summary)
    due_suffix = f" (due: {item.due_date.isoformat()})" if item.due_date else " (due: N/A)"
    if jira_base_url:
        issue_url = f"{jira_base_url}/browse/{item.issue_key}"
        issue_anchor = f'<a href="{html_lib.escape(issue_url, quote=True)}">{escaped_issue}</a>'
        return f"- {issue_anchor}: {escaped_summary}{due_suffix}"
    return f"- {escaped_issue}: {escaped_summary}{due_suffix}"


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
        lookback_hours: int = 24,
        completed_status_names: list[str] | None = None,
    ) -> None:
        self.jira_client = jira_client
        self.users_store = users_store
        self.project_key = project_key
        # Important: do NOT re-use a single telegram.Bot instance across multiple
        # asyncio.run() calls. Each send uses its own event-loop lifecycle.
        self._bot_token = bot_token
        self.logger = logger
        self._lookback_hours = lookback_hours
        self._completed_status_names: list[str] = (
            list(completed_status_names) if completed_status_names else ["Done"]
        )

    def build_report(self, *, window_days: int, now: datetime) -> ReportModel:
        """
        Dựng ReportModel theo contract Phase 5: quá hạn < today; sắp đến hạn trong [today, today+N].
        Assignee không có mapping Telegram bị bỏ (trừ Unassigned).
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware datetime")

        today = now.date()
        reverse_map = self.users_store.get_reverse_mapping()  # jira_id -> telegram_username

        query = QueryIssuesRequest(
            project_key=self.project_key,
            reporter_account_id="",  # Không lọc reporter trong JQL
            window_days=window_days,
            now=now,
        )
        grouped: dict[str, list[JiraIssueRecord]] = self.jira_client.query_issues_by_due_date_for_reporter(query)

        by_assignee: dict[str, AssigneeReport] = {}
        for group_key, records in grouped.items():
            assignee_key_norm = (group_key or "").strip().lower()
            is_unassigned = (not group_key) or assignee_key_norm == "unassigned"

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
                    if due <= (today + timedelta(days=window_days)):
                        upcoming_items.append(issue)

            if not is_unassigned:
                tuser = reverse_map.get(str(group_key).strip())
                if not tuser:
                    continue
                rec = self.users_store.get_user_record_by_user_name(tuser)
                mention_text = _format_report_assignee_mention(telegram_username=tuser, record=rec)
            else:
                tuser = None
                mention_text = "Unassigned"

            overdue_items.sort(key=lambda x: (x.due_date or date.min, x.issue_key))
            upcoming_items.sort(key=lambda x: (x.due_date or date.min, x.issue_key))

            if overdue_items or upcoming_items:
                by_assignee[group_key] = AssigneeReport(
                    telegram_username=tuser,
                    assignee_mention_text=mention_text,
                    overdue=overdue_items,
                    upcoming=upcoming_items,
                    completed_recent=[],
                )

        completed_req = QueryRecentlyCompletedRequest(
            project_key=self.project_key,
            now=now,
            lookback_hours=self._lookback_hours,
            completed_status_names=self._completed_status_names,
        )
        completed_fn = getattr(self.jira_client, "query_issues_completed_in_window", None)
        completed_grouped: dict[str, list[JiraIssueRecord]] = (
            completed_fn(completed_req) if callable(completed_fn) else {}
        )

        for group_key, records in completed_grouped.items():
            if not records:
                continue
            assignee_key_norm = (group_key or "").strip().lower()
            is_unassigned = (not group_key) or assignee_key_norm == "unassigned"

            if not is_unassigned:
                tuser = reverse_map.get(str(group_key).strip())
                if not tuser:
                    continue
                rec = self.users_store.get_user_record_by_user_name(tuser)
                mention_text = _format_report_assignee_mention(telegram_username=tuser, record=rec)
            else:
                tuser = None
                mention_text = "Unassigned"

            completed_items: list[ReportIssue] = []
            for record in records:
                due_parsed: date | None = None
                if record.due_date:
                    try:
                        due_parsed = date.fromisoformat(record.due_date)
                    except ValueError:
                        due_parsed = None
                completed_items.append(
                    ReportIssue(issue_key=record.issue_key, summary=record.summary, due_date=due_parsed)
                )
            completed_items.sort(
                key=lambda x: (x.due_date is None, x.due_date or date.min, x.issue_key),
            )

            existing = by_assignee.get(group_key)
            if existing:
                existing.completed_recent = completed_items
            elif completed_items:
                by_assignee[group_key] = AssigneeReport(
                    telegram_username=tuser,
                    assignee_mention_text=mention_text,
                    overdue=[],
                    upcoming=[],
                    completed_recent=completed_items,
                )

        def _assignee_sort_key(a: AssigneeReport) -> tuple[int, str]:
            if a.telegram_username is None:
                return (1, "")
            return (0, a.telegram_username.lower())

        assignee_reports = list(by_assignee.values())
        assignee_reports.sort(key=_assignee_sort_key)

        total_upcoming = sum(len(a.upcoming) for a in assignee_reports)
        total_overdue = sum(len(a.overdue) for a in assignee_reports)
        total_completed_24h = sum(len(a.completed_recent) for a in assignee_reports)

        return ReportModel(
            today=today,
            window_days=window_days,
            total_upcoming=total_upcoming,
            total_overdue=total_overdue,
            total_completed_24h=total_completed_24h,
            assignees=assignee_reports,
        )

    def build_report_messages(self, *, window_days: int, now: datetime) -> list[str]:
        """Chuyển ReportModel thành list tin nhắn (block 1 tổng + mỗi assignee một tin)."""
        model = self.build_report(window_days=window_days, now=now)

        overall_text = (
            f"Tổng sắp đến hạn: {model.total_upcoming}\n"
            f"Tổng quá hạn: {model.total_overdue}\n"
            f"Tổng đã hoàn thành trong {self._lookback_hours}h qua: {model.total_completed_24h}"
        )

        messages: list[str] = [overall_text]

        jira_base_url = getattr(self.jira_client, "base_url", "") or ""
        jira_base_url = jira_base_url.rstrip("/")

        for assignee in model.assignees:
            escaped_assignee = html_lib.escape(assignee.assignee_mention_text)
            section_blocks: list[str] = []
            if assignee.overdue:
                block_lines = ["Quá hạn:"]
                for item in assignee.overdue:
                    block_lines.append(_format_report_issue_line(item=item, jira_base_url=jira_base_url))
                section_blocks.append("\n".join(block_lines))
            if assignee.upcoming:
                block_lines = ["Sắp đến hạn:"]
                for item in assignee.upcoming:
                    block_lines.append(_format_report_issue_line(item=item, jira_base_url=jira_base_url))
                section_blocks.append("\n".join(block_lines))
            if assignee.completed_recent:
                block_lines = [f"Đã hoàn thành trong {self._lookback_hours}h qua"]
                for item in assignee.completed_recent:
                    block_lines.append(_format_report_issue_line(item=item, jira_base_url=jira_base_url))
                section_blocks.append("\n".join(block_lines))
            body = "\n\n".join(section_blocks)
            messages.append(f"Assignee: {escaped_assignee}\n{body}")

        return messages

    async def _send_messages_async(self, *, telegram_chat_id: int, message_texts: list[str]) -> None:
        """Gửi tuần tự từng tin với parse_mode HTML."""
        # Create a fresh Bot per send invocation to avoid cross-event-loop side effects.
        bot = Bot(token=self._bot_token)
        for idx, text in enumerate(message_texts):
            try:
                await bot.send_message(chat_id=telegram_chat_id, text=text, parse_mode="HTML")
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

