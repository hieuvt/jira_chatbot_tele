"""
Test render báo cáo Reporter (không mạng): quá hạn/sắp đến hạn, sort, HTML/plain.

Kiểm tra:
- Ranh giới quá hạn (< today) và sắp đến hạn ([today, today+N])
- Lọc assignee theo mapping users.json
- Nhóm Unassigned vẫn render dù không có mapping
- Thứ tự: assignee theo telegram_id tăng, Unassigned cuối; issue theo due rồi key
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

    def query_issues_by_due_date_for_reporter(self, query: Any) -> dict[str, list[JiraIssueRecord]]:  # noqa: ANN401
        _ = query
        return self.grouped_issues


def main() -> int:
    failures = 0

    # Use UTC for tests: environment may not ship tzdata for "Asia/Ho_Chi_Minh".
    # Reporter classification uses only now.date() (overdue/upcoming based on "today").
    now = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
    window_days = 3

    # users.json: array of records (telegram_id <-> jira_id); reverse map for reporter
    with tempfile.TemporaryDirectory() as tmp:
        users_path = Path(tmp) / "users.json"
        users_path.write_text(
            json.dumps(
                [
                    {
                        "user_name": "fallback_two",
                        "telegram_id": "2",
                        "telegram_display_name": "User Two",
                        "jira_id": "jira-2",
                    },
                    {
                        "user_name": "fallback_ten",
                        "telegram_id": "10",
                        "telegram_display_name": "User Ten",
                        "jira_id": "jira-1",
                    },
                ]
            ),
            encoding="utf-8",
        )
        users_store = UsersStore(users_path)

        grouped: dict[str, list[JiraIssueRecord]] = {
            # telegram "10"
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
            # telegram "2"
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

        reporter = Reporter(
            jira_client=FakeJiraClient(grouped_issues=grouped),
            users_store=users_store,
            project_key="OM",
            bot_token="TEST_TOKEN",
            logger=None,
        )

        messages = reporter.build_report_messages(window_days=window_days, now=now)

        # Block 1 totals
        expected_upcoming = 4  # jira-1: 3, jira-2: 1
        expected_overdue = 2  # jira-1: 1, unassigned: 1
        failures += _check(
            messages[0] == f"Tổng sắp đến hạn: {expected_upcoming}\nTổng quá hạn: {expected_overdue}",
            "Block 1 exact totals text",
        )

        # Included assignees only: telegram id 2, telegram id 10, Unassigned => 3 block2 messages + block1
        failures += _check(len(messages) == 4, "Total messages count (block1 + 3 assignees)")

        # Assignee order: telegram "2" first, "10" second, Unassigned last (@ from user_name)
        failures += _check(messages[1].startswith("Assignee: @fallback_two\n"), "Assignee order: telegram 2 first")
        failures += _check(messages[2].startswith("Assignee: @fallback_ten\n"), "Assignee order: telegram 10 second")
        failures += _check(messages[3].startswith("Assignee: Unassigned\n"), "Assignee order: Unassigned last")

        # Assignee '2': only upcoming => no "Quá hạn:" heading
        lines_2 = messages[1].splitlines()
        failures += _check(lines_2[0] == "Assignee: @fallback_two", "Assignee '2' first line (@ user_name)")
        failures += _check("Quá hạn:" not in lines_2, "Assignee '2' should not include Quá hạn section")
        failures += _check(lines_2[1] == "Sắp đến hạn:", "Assignee '2' should have Sắp đến hạn heading")
        failures += _check(
            lines_2[2] == "- OM-050: Upcoming B (due: 2026-03-20)",
            "Assignee '2' issue line formatting",
        )

        # Assignee '10': overdue + upcoming => has blank line exactly once between headings
        lines_10 = messages[2].splitlines()
        # Expected layout:
        # 0 Assignee: 10
        # 1 Quá hạn:
        # 2 - OM-100: Overdue A (due: 2026-03-19)
        # 3 (blank)
        # 4 Sắp đến hạn:
        failures += _check(lines_10[0] == "Assignee: @fallback_ten", "Assignee '10' first line (@ user_name)")
        failures += _check(lines_10[1] == "Quá hạn:", "Assignee '10' has Quá hạn heading")
        failures += _check(lines_10[2] == "- OM-100: Overdue A (due: 2026-03-19)", "Assignee '10' overdue issue")
        failures += _check(lines_10[3] == "", "Assignee '10' has exactly 1 blank line between sections")
        failures += _check(lines_10[4] == "Sắp đến hạn:", "Assignee '10' has Sắp đến hạn heading")

        # Upcoming ordering inside assignee '10':
        # due 2026-03-20 (OM-099) -> 2026-03-22 (OM-102) -> 2026-03-23 (OM-101)
        failures += _check(lines_10[5] == "- OM-099: Upcoming T (due: 2026-03-20)", "Upcoming sorting 1")
        failures += _check(lines_10[6] == "- OM-102: Upcoming C (due: 2026-03-22)", "Upcoming sorting 2")
        failures += _check(lines_10[7] == "- OM-101: Upcoming D (due: 2026-03-23)", "Upcoming sorting 3")
        failures += _check("" not in lines_10[5:8], "No blank lines between issue lines (assignee '10')")

        # Unassigned: only overdue => no upcoming heading
        lines_u = messages[3].splitlines()
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

