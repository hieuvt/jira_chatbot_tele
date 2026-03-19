"""Phase 2 smoke test for JiraClient.

Usage:
  python scripts/phase2_smoke_test.py --assignee-account-id <jiraAccountId> --reporter-account-id <jiraAccountId>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from phase2_test_common import build_jira_client, get_jira_settings, load_runtime_config
from src.common.errors import JiraClientError
from src.jira.models import AttachmentMeta, IssueCreateRequest, QueryIssuesRequest, SubtaskCreateRequest


def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Windows Python often requires tzdata package. Fallback keeps smoke test executable.
        return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh_Fallback")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 2 JiraClient smoke tests.")
    parser.add_argument("--config", default="config/config.json", help="Path to runtime config JSON.")
    parser.add_argument("--assignee-account-id", required=True, help="Jira accountId used for issue assignee.")
    parser.add_argument("--reporter-account-id", required=True, help="Jira accountId used for due-date query.")
    parser.add_argument("--skip-upload", action="store_true", help="Skip attachment upload step.")
    return parser.parse_args()


def print_error(step: str, exc: JiraClientError) -> None:
    print(f"[{step}] FAIL")
    print(f"  code      : {exc.code}")
    print(f"  message   : {exc.message}")
    print(f"  retriable : {exc.retriable}")
    print(f"  context   : {exc.context}")


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    jira = get_jira_settings(config)
    client = build_jira_client(config)

    timezone_name = str(jira.get("timezone", "Asia/Ho_Chi_Minh"))
    tz = _resolve_timezone(timezone_name)
    now = datetime.now(tz=tz)
    due_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    issue_key = ""

    try:
        is_member = client.check_project_membership(args.assignee_account_id, str(jira["project_key"]))
        print(f"[membership] OK member={is_member}")
    except JiraClientError as exc:
        print_error("membership", exc)
        return 1

    try:
        is_admin = client.check_project_admin(args.assignee_account_id, str(jira["project_key"]))
        print(f"[admin] OK admin={is_admin}")
    except JiraClientError as exc:
        print_error("admin", exc)
        return 1

    try:
        issue_key = client.create_issue(
            IssueCreateRequest(
                project_key=str(jira["project_key"]),
                summary=f"[PHASE2 SMOKE] {now.isoformat()}",
                description="Smoke test main issue",
                assignee_account_id=args.assignee_account_id,
                due_date=due_date,
                issue_type_id=str(jira["issue_type_id"]),
            )
        )
        print(f"[create_issue] OK issue_key={issue_key}")
    except JiraClientError as exc:
        print_error("create_issue", exc)
        return 1

    try:
        sub_keys = client.create_subtasks(
            SubtaskCreateRequest(
                parent_issue_key=issue_key,
                issue_type_id=str(jira["subtask_issue_type_id"]),
                checklist_items=["Smoke subtask 1", "Smoke subtask 2"],
            )
        )
        print(f"[create_subtasks] OK subtasks={sub_keys}")
    except JiraClientError as exc:
        print_error("create_subtasks", exc)
        return 1

    if not args.skip_upload:
        try:
            content = f"phase2 smoke upload {now.isoformat()}".encode("utf-8")
            attachment_ids = client.upload_attachments(
                issue_key=issue_key,
                files=[
                    AttachmentMeta(
                        filename="phase2-smoke.txt",
                        size_bytes=len(content),
                        telegram_file_id="local-smoke",
                        content_bytes=content,
                        content_type="text/plain",
                    )
                ],
            )
            print(f"[upload_attachments] OK attachment_ids={attachment_ids}")
        except JiraClientError as exc:
            print_error("upload_attachments", exc)
            return 1
    else:
        print("[upload_attachments] SKIPPED")

    try:
        q = QueryIssuesRequest(
            project_key=str(jira["project_key"]),
            reporter_account_id=args.reporter_account_id,
            window_days=int(config.get("due", {}).get("notification", {}).get("window_days", 3)),
            now=now,
            max_results=int(jira.get("search", {}).get("max_results", 50)),
            max_pages=int(jira.get("search", {}).get("max_pages", 20)),
        )
        grouped = client.query_issues_by_due_date_for_reporter(q)
        total = sum(len(items) for items in grouped.values())
        print(f"[query_due_issues] OK assignee_groups={len(grouped)} total_issues={total}")
    except JiraClientError as exc:
        print_error("query_due_issues", exc)
        return 1

    print("PHASE 2 SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
