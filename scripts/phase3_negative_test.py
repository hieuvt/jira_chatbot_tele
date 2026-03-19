"""Phase 3 negative tests for Telegram conversation state machine.

Usage:
  python scripts/phase3_negative_test.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from phase3_test_common import build_state_machine, make_attachment, make_text
from src.common.errors import JiraClientError


def _check(condition: bool, label: str) -> int:
    if condition:
        print(f"[OK] {label}")
        return 0
    print(f"[FAIL] {label}")
    return 1


def test_unknown_intent() -> int:
    machine, _, _ = build_state_machine()
    failures = 0
    msg = machine.handle_message(make_text(3001, 7001, "abc xyz"))
    failures += _check("Mình chưa hiểu yêu cầu" in msg, "unknown intent template")
    msg = machine.handle_message(make_text(3001, 7001, "giao việc"))
    failures += _check("Mình chưa hiểu yêu cầu" in msg, "plain text command rejected")
    msg = machine.handle_message(make_text(3001, 7001, "@hieuvt1_bot giao việc"))
    failures += _check("Mình chưa hiểu yêu cầu" in msg, "mention command rejected")
    return failures


def test_invalid_due_days() -> int:
    sender = "jira-user-7101"
    machine, _, _ = build_state_machine(user_mapping={"7101": sender}, member_ids={sender})
    chat_id = 3002
    user_id = 7101
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi"))
    machine.handle_message(make_text(chat_id, user_id, "Summary A"))
    machine.handle_message(make_text(chat_id, user_id, "Description A"))
    machine.handle_message(make_text(chat_id, user_id, "không"))
    machine.handle_message(make_text(chat_id, user_id, "không"))
    msg = machine.handle_message(make_text(chat_id, user_id, "3.5"))
    return _check("Giá trị không hợp lệ" in msg, "invalid due days")


def test_not_admin_assign() -> int:
    sender = "jira-user-7201"
    machine, _, _ = build_state_machine(
        user_mapping={"7201": sender},
        member_ids={sender},
        admin_ids=set(),
    )
    msg = machine.handle_message(make_text(3003, 7201, "/giaoviec"))
    return _check("Chỉ Admin của project mới có quyền giao việc" in msg, "member cannot assign others")


def test_attachment_limits() -> int:
    sender = "jira-user-7301"
    machine, _, _ = build_state_machine(
        user_mapping={"7301": sender},
        member_ids={sender},
    )
    chat_id = 3004
    user_id = 7301
    failures = 0
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi"))
    machine.handle_message(make_text(chat_id, user_id, "Summary limits"))
    machine.handle_message(make_text(chat_id, user_id, "Description limits"))
    # single-file max (default from config is 10MB)
    msg = machine.handle_message(make_attachment(chat_id, user_id, "too-big.txt", 11 * 1024 * 1024, b"x"))
    failures += _check("File vượt kích thước cho phép" in msg, "single file size limit")
    # max files (default 10)
    for i in range(10):
        machine.handle_message(make_attachment(chat_id, user_id, f"f{i}.txt", 1, b"x"))
    msg = machine.handle_message(make_attachment(chat_id, user_id, "overflow.txt", 1, b"x"))
    failures += _check("vượt quá số lượng file cho phép" in msg, "max files limit")
    return failures


def test_timeout() -> int:
    sender = "jira-user-7401"
    machine, _, _ = build_state_machine(user_mapping={"7401": sender}, member_ids={sender})
    chat_id = 3005
    user_id = 7401
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi"))
    # force timeout by mutating in-memory buffer timestamp
    session = machine._sessions[(chat_id, user_id)]  # noqa: SLF001
    session.updated_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    msg = machine.handle_message(make_text(chat_id, user_id, "abc"))
    return _check("Mình chưa hiểu yêu cầu" in msg, "timeout clears session and treats next message as new")


def test_jira_error_mapping() -> int:
    sender = "jira-user-7501"
    machine, _, _ = build_state_machine(
        user_mapping={"7501": sender},
        member_ids={sender},
        jira_overrides={
            "create": JiraClientError(
                code="JIRA_RATE_LIMITED",
                message="rate",
                context={},
                retriable=True,
            )
        },
    )
    chat_id = 3006
    user_id = 7501
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi"))
    machine.handle_message(make_text(chat_id, user_id, "Summary rate limit"))
    machine.handle_message(make_text(chat_id, user_id, "Description rate limit"))
    machine.handle_message(make_text(chat_id, user_id, "không"))
    machine.handle_message(make_text(chat_id, user_id, "không"))
    machine.handle_message(make_text(chat_id, user_id, "2"))
    msg = machine.handle_message(make_text(chat_id, user_id, "có"))
    return _check("Jira đang giới hạn tần suất" in msg, "jira error code mapping")


def main() -> int:
    failures = 0
    failures += test_unknown_intent()
    failures += test_invalid_due_days()
    failures += test_not_admin_assign()
    failures += test_attachment_limits()
    failures += test_timeout()
    failures += test_jira_error_mapping()
    if failures:
        print(f"PHASE 3 NEGATIVE TEST FAILED with {failures} issue(s)")
        return 1
    print("PHASE 3 NEGATIVE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
