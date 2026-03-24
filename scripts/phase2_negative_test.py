"""Test âm tính Jira client: due date sai định dạng, vượt giới hạn sub-task.

Usage:
  python scripts/phase2_negative_test.py --assignee-account-id <jiraAccountId>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from phase2_test_common import build_jira_client, get_jira_settings, load_runtime_config
from src.common.errors import JiraClientError
from src.jira.models import IssueCreateRequest, SubtaskCreateRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run negative tests for Phase 2 JiraClient.")
    parser.add_argument("--config", default="config/config.json", help="Path to runtime config JSON.")
    parser.add_argument("--assignee-account-id", required=True, help="Jira accountId used in request payload.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    jira = get_jira_settings(config)
    client = build_jira_client(config)
    failures = 0

    print("[negative] expecting JIRA_INVALID_DUE_DATE")
    try:
        client.create_issue(
            IssueCreateRequest(
                project_key=str(jira["project_key"]),
                summary="[NEGATIVE] invalid due date",
                description="expect invalid due date",
                assignee_account_id=args.assignee_account_id,
                due_date="2026/03/19",
                issue_type_id=str(jira["issue_type_id"]),
            )
        )
        print("  FAIL expected exception, got success")
        failures += 1
    except JiraClientError as exc:
        if exc.code == "JIRA_INVALID_DUE_DATE":
            print("  OK got expected code:", exc.code)
        else:
            print("  FAIL unexpected code:", exc.code)
            failures += 1

    print("[negative] expecting JIRA_SUBTASK_LIMIT_EXCEEDED")
    try:
        client.create_subtasks(
            SubtaskCreateRequest(
                parent_issue_key=f"{jira['project_key']}-1",
                issue_type_id=str(jira["subtask_issue_type_id"]),
                checklist_items=[f"item {i}" for i in range(21)],
            )
        )
        print("  FAIL expected exception, got success")
        failures += 1
    except JiraClientError as exc:
        if exc.code == "JIRA_SUBTASK_LIMIT_EXCEEDED":
            print("  OK got expected code:", exc.code)
        else:
            print("  FAIL unexpected code:", exc.code)
            failures += 1

    if failures:
        print(f"NEGATIVE TEST FAILED with {failures} issue(s)")
        return 1
    print("NEGATIVE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
