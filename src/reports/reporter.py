"""Phase 5: Scheduler & Reporter implementation.

Build periodic due-date report:
- Overdue: due_date < today
- Upcoming: today <= due_date <= today+N (inclusive)

Then group by assignee and filter by mapping in users.json (telegram <-> jira).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import html as html_lib
from typing import Any

from telegram import Bot

from src.jira.models import JiraIssueRecord, QueryIssuesRequest
from src.storage.users_store import UsersStore


@dataclass(frozen=True)
class ReportIssue:
    issue_key: str
    summary: str
    due_date: date


@dataclass
class AssigneeReport:
    label: str  # telegram_account_id or "Unassigned"
    overdue: list[ReportIssue]
    upcoming: list[ReportIssue]


@dataclass
class ReportModel:
    today: date
    window_days: int
    total_upcoming: int
    total_overdue: int
    assignees: list[AssigneeReport]


class Reporter:
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
        Build report model that matches Documents/PHASE_05_Scheduler_And_Reporter.md contract.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware datetime")

        today = now.date()
        reverse_map = self.users_store.get_reverse_mapping()  # jira_account_id -> telegram_account_id

        query = QueryIssuesRequest(
            project_key=self.project_key,
            reporter_account_id="",  # Phase 5 contract: no reporter filter
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
                    # Upcoming window is inclusive: today..today+N
                    if due <= (today + timedelta(days=window_days)):
                        upcoming_items.append(issue)

            # Filter mapping Telegram:
            # - Unassigned group is always rendered
            # - Other assignees are rendered only if they have reverse mapping (jira_account_id -> telegram_account_id)
            if not is_unassigned:
                telegram_id = reverse_map.get(str(assignee_jira_id).strip())
                if not telegram_id:
                    continue
                label = telegram_id
            else:
                label = "Unassigned"

            # Sort issues in each part: due_date asc, then issue_key asc
            overdue_items.sort(key=lambda x: (x.due_date, x.issue_key))
            upcoming_items.sort(key=lambda x: (x.due_date, x.issue_key))

            if overdue_items or upcoming_items:
                assignee_reports.append(
                    AssigneeReport(label=label, overdue=overdue_items, upcoming=upcoming_items)
                )

        # Sort assignees: telegram_account_id asc, Unassigned last
        def _assignee_sort_key(a: AssigneeReport) -> tuple[int, int, int]:
            if a.label == "Unassigned":
                return (1, 0, 0)
            try:
                # Telegram IDs are numeric most of the time; use int ordering.
                return (0, 0, int(a.label))
            except Exception:
                # Non-numeric label: keep them after numeric IDs.
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
        model = self.build_report(window_days=window_days, now=now)

        # Block 1: only 2 lines (no header time).
        overall_text = f"Tổng sắp đến hạn: {model.total_upcoming}\nTổng quá hạn: {model.total_overdue}"

        messages: list[str] = [overall_text]

        jira_base_url = getattr(self.jira_client, "base_url", "") or ""
        jira_base_url = jira_base_url.rstrip("/")

        for assignee in model.assignees:
            lines: list[str] = [f"Assignee: {assignee.label}"]

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
                # One empty line between overdue and upcoming headings (only if both exist).
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
        for idx, text in enumerate(message_texts):
            try:
                await self._bot.send_message(chat_id=telegram_chat_id, text=text, parse_mode="HTML")
            except Exception as exc:
                raise

    def send_report(self, *, telegram_chat_id: int, message_texts: list[str] | str) -> None:
        """
        Send report messages sequentially.

        Note: this method is sync (used by APScheduler job thread),
        so it runs an event loop internally.
        """
        texts: list[str] = [message_texts] if isinstance(message_texts, str) else message_texts
        asyncio.run(self._send_messages_async(telegram_chat_id=telegram_chat_id, message_texts=texts))

    # Backward-compatible methods (not used yet by scheduler wiring).
    def get_due_tasks(self, window_days: int, now: datetime) -> dict[str, list[dict[str, str]]]:
        _ = (window_days, now)
        return {}

    def render_report(self, issues: dict[str, list[dict[str, str]]]) -> str:
        _ = issues
        return "Báo cáo định kỳ (unimplemented legacy renderer)"

