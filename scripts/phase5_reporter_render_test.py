"""
Test render báo cáo Reporter (không mạng): quá hạn/sắp đến hạn, sort, HTML/plain.

Kiểm tra:
- Ranh giới quá hạn (< today) và sắp đến hạn ([today, today+N])
- Lọc assignee theo mapping users.json
- Nhóm Unassigned vẫn render dù không có mapping
- Thứ tự: assignee theo user_name (chuỗi) tăng, Unassigned cuối; issue theo due rồi key
- Định dạng: block 1 hai dòng tổng; block 2 heading chỉ khi có issue; một dòng trống giữa hai mục khi cả hai có dữ liệu
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.jira.models import JiraIssueRecord
from src.reports.reporter import Reporter
from src.storage.users_store import UsersStore


def _check(cond: bool, label: str) -> int:
    if cond:
        safe_label = label.encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"[OK] {safe_label}")
        return 0
    safe_label = label.encode("ascii", errors="backslashreplace").decode("ascii")
    print(f"[FAIL] {safe_label}")
    return 1


@dataclass
class FakeJiraClient:
    grouped_issues: dict[str, list[JiraIssueRecord]]
    completed_issues: dict[str, list[JiraIssueRecord]] | None = None
    completed_issue_has_image: dict[str, bool] | None = None

    def query_issues_by_due_date_for_reporter(self, query: Any) -> dict[str, list[JiraIssueRecord]]:  # noqa: ANN401
        _ = query
        return self.grouped_issues

    def query_issues_completed_in_window(self, query: Any) -> dict[str, list[JiraIssueRecord]]:  # noqa: ANN401
        _ = query
        return self.completed_issues or {}

    def latest_comment_has_image(self, issue_key: str) -> bool:
        return bool((self.completed_issue_has_image or {}).get(issue_key, False))


def main() -> int:
    failures = 0

    # Use UTC for tests: environment may not ship tzdata for "Asia/Ho_Chi_Minh".
    # Reporter classification uses only now.date() (overdue/upcoming based on "today").
    now = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
    window_days = 3

    # users.json: @username (user_name) <-> jira_id; reverse map for reporter
    with tempfile.TemporaryDirectory() as tmp:
        users_path = Path(tmp) / "users.json"
        users_path.write_text(
            json.dumps(
                [
                    {
                        "user_name": "fallback_two",
                        "telegram_display_name": "User Two",
                        "jira_id": "jira-2",
                    },
                    {
                        "user_name": "fallback_ten",
                        "telegram_display_name": "User Ten",
                        "jira_id": "jira-1",
                    },
                    {
                        "user_name": "only_done",
                        "telegram_display_name": "Only Done",
                        "jira_id": "jira-3",
                    },
                ]
            ),
            encoding="utf-8",
        )
        users_store = UsersStore(users_path)

        grouped: dict[str, list[JiraIssueRecord]] = {
            # fallback_ten / jira-1
            "jira-1": [
                JiraIssueRecord(
                    issue_key="OM-101",
                    summary="Upcoming D",
                    due_date="2026-03-23",
                    status="To Do",
                    assignee_account_id="jira-1",
                ),
                JiraIssueRecord(
                    issue_key="OM-099",
                    summary="Upcoming T",
                    due_date="2026-03-20",
                    status="To Do",
                    assignee_account_id="jira-1",
                ),
                JiraIssueRecord(
                    issue_key="OM-100",
                    summary="Overdue A",
                    due_date="2026-03-19",
                    status="To Do",
                    assignee_account_id="jira-1",
                ),
                JiraIssueRecord(
                    issue_key="OM-102",
                    summary="Upcoming C",
                    due_date="2026-03-22",
                    status="To Do",
                    assignee_account_id="jira-1",
                ),
            ],
            # fallback_two / jira-2
            "jira-2": [
                JiraIssueRecord(
                    issue_key="OM-050",
                    summary="Upcoming B",
                    due_date="2026-03-20",
                    status="To Do",
                    assignee_account_id="jira-2",
                )
            ],
            # no mapping => excluded
            "jira-no-map": [
                JiraIssueRecord(
                    issue_key="OM-999",
                    summary="Should be excluded",
                    due_date="2026-03-21",
                    status="To Do",
                    assignee_account_id="jira-no-map",
                )
            ],
            # Unassigned (lowercase group key "unassigned" matches Reporter contract)
            "unassigned": [
                JiraIssueRecord(
                    issue_key="OM-300",
                    summary="Overdue U",
                    due_date="2026-03-18",
                    status="To Do",
                    assignee_account_id=None,
                )
            ],
        }

        completed: dict[str, list[JiraIssueRecord]] = {
            "jira-1": [
                JiraIssueRecord(
                    issue_key="OM-40",
                    summary="review Phase 1 Huy",
                    due_date="2026-03-25",
                    status="Done",
                    assignee_account_id="jira-1",
                    status_category_key="done",
                ),
            ],
            "jira-3": [
                JiraIssueRecord(
                    issue_key="OM-77",
                    summary="Chỉ có completed",
                    due_date=None,
                    status="Done",
                    assignee_account_id="jira-3",
                    status_category_key="done",
                ),
            ],
        }

        reporter = Reporter(
            jira_client=FakeJiraClient(
                grouped_issues=grouped,
                completed_issues=completed,
                completed_issue_has_image={
                    "OM-40": True,
                    "OM-77": False,
                },
            ),
            users_store=users_store,
            project_key="OM",
            bot_token="TEST_TOKEN",
            logger=None,
        )

        messages = reporter.build_report_messages(window_days=window_days, now=now)

        # Block 1 totals
        expected_upcoming = 4  # jira-1: 3, jira-2: 1
        expected_overdue = 2  # jira-1: 1, unassigned: 1
        expected_completed = 2  # jira-1: 1, jira-3: 1
        failures += _check(
            messages[0]
            == (
                f"Tổng sắp đến hạn: {expected_upcoming}\n"
                f"Tổng quá hạn: {expected_overdue}\n"
                f"Tổng đã hoàn thành trong 24h qua: {expected_completed}"
            ),
            "Block 1 exact totals text",
        )

        # Included assignees: fallback_ten, fallback_two, only_done, Unassigned => 4 block2 + block1
        failures += _check(len(messages) == 5, "Total messages count (block1 + 4 assignees)")

        # Assignee order: fallback_ten < fallback_two < only_done lexicographically, Unassigned last
        failures += _check(messages[1].startswith("Assignee: @fallback_ten\n"), "Assignee order: fallback_ten first")
        failures += _check(messages[2].startswith("Assignee: @fallback_two\n"), "Assignee order: fallback_two second")
        failures += _check(messages[3].startswith("Assignee: @only_done\n"), "Assignee order: only_done third")
        failures += _check(messages[4].startswith("Assignee: Unassigned\n"), "Assignee order: Unassigned last")

        # Assignee jira-1 (fallback_ten): overdue + upcoming => has blank line exactly once between headings
        lines_ten = messages[1].splitlines()
        failures += _check(lines_ten[0] == "Assignee: @fallback_ten", "Assignee fallback_ten first line (@ user_name)")
        failures += _check(lines_ten[1] == "Quá hạn:", "Assignee fallback_ten has Quá hạn heading")
        failures += _check(lines_ten[2] == "- OM-100: Overdue A (due: 2026-03-19)", "Assignee fallback_ten overdue issue")
        failures += _check(lines_ten[3] == "", "Assignee fallback_ten has exactly 1 blank line between sections")
        failures += _check(lines_ten[4] == "Sắp đến hạn:", "Assignee fallback_ten has Sắp đến hạn heading")

        # Upcoming ordering inside assignee jira-1:
        failures += _check(lines_ten[5] == "- OM-099: Upcoming T (due: 2026-03-20)", "Upcoming sorting 1")
        failures += _check(lines_ten[6] == "- OM-102: Upcoming C (due: 2026-03-22)", "Upcoming sorting 2")
        failures += _check(lines_ten[7] == "- OM-101: Upcoming D (due: 2026-03-23)", "Upcoming sorting 3")
        failures += _check("" not in lines_ten[5:8], "No blank lines between issue lines (fallback_ten)")
        failures += _check(lines_ten[8] == "", "Blank line before completed section")
        failures += _check(lines_ten[9] == "Đã hoàn thành trong 24h qua", "Completed section heading")
        failures += _check(
            lines_ten[10] == "- OM-40: review Phase 1 Huy (due: 2026-03-25) — có ảnh minh họa",
            "Completed issue line (no base_url in fake client)",
        )

        # Assignee jira-2 (fallback_two): only upcoming => no "Quá hạn:" heading
        lines_two = messages[2].splitlines()
        failures += _check(lines_two[0] == "Assignee: @fallback_two", "Assignee fallback_two first line (@ user_name)")
        failures += _check("Quá hạn:" not in lines_two, "Assignee fallback_two should not include Quá hạn section")
        failures += _check(lines_two[1] == "Sắp đến hạn:", "Assignee fallback_two should have Sắp đến hạn heading")
        failures += _check(
            lines_two[2] == "- OM-050: Upcoming B (due: 2026-03-20)",
            "Assignee fallback_two issue line formatting",
        )

        # only_done: chỉ completed + due N/A
        lines_od = messages[3].splitlines()
        failures += _check(lines_od[0] == "Assignee: @only_done", "only_done first line")
        failures += _check(lines_od[1] == "Đã hoàn thành trong 24h qua", "only_done has only completed heading")
        failures += _check(
            lines_od[2] == "- OM-77: Chỉ có completed (due: N/A) — KHÔNG có ảnh minh họa",
            "only_done issue due N/A when duedate empty",
        )
        failures += _check("Quá hạn:" not in lines_od and "Sắp đến hạn:" not in lines_od, "only_done no due sections")

        # Unassigned: only overdue => no upcoming heading
        lines_u = messages[4].splitlines()
        failures += _check(lines_u[0] == "Assignee: Unassigned", "Unassigned first line")
        failures += _check("Sắp đến hạn:" not in lines_u, "Unassigned should not include Sắp đến hạn section")
        failures += _check(lines_u[1] == "Quá hạn:", "Unassigned has Quá hạn heading")
        failures += _check(
            lines_u[2] == "- OM-300: Overdue U (due: 2026-03-18)",
            "Unassigned overdue issue formatting",
        )

        # Ensure excluded assignee not present anywhere
        failures += _check("Should be excluded" not in "\n".join(messages), "Unmapped assignee excluded")

    # Final
    if failures:
        print(f"PHASE 5 REPORTER RENDER TEST FAILED with {failures} failure(s)")
        return 1
    print("PHASE 5 REPORTER RENDER TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

