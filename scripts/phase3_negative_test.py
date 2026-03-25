"""Test âm tính state machine: intent lạ, due days, file, /huy, timeout, lỗi Jira.

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
    tg_user = "u7101"
    machine, _, _ = build_state_machine(user_mapping={tg_user: sender}, member_ids={sender})
    chat_id = 3002
    user_id = 7101
    su = dict(sender_username=tg_user)
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    machine.handle_message(make_text(chat_id, user_id, "Summary A", **su))
    machine.handle_message(make_text(chat_id, user_id, "Description A", **su))
    machine.handle_message(make_text(chat_id, user_id, "không", **su))
    machine.handle_message(make_text(chat_id, user_id, "không", **su))
    msg = machine.handle_message(make_text(chat_id, user_id, "3.5", **su))
    return _check("Giá trị không hợp lệ" in msg, "invalid due days")


def test_not_admin_assign() -> int:
    sender = "jira-user-7201"
    tg_user = "u7201"
    machine, _, _ = build_state_machine(
        user_mapping={tg_user: sender},
        member_ids={sender},
        admin_ids=set(),
    )
    msg = machine.handle_message(make_text(3003, 7201, "/giaoviec", sender_username=tg_user))
    return _check("Chỉ Admin của project mới có quyền giao việc" in msg, "member cannot assign others")


def test_attachment_limits() -> int:
    sender = "jira-user-7301"
    tg_user = "u7301"
    machine, _, _ = build_state_machine(
        user_mapping={tg_user: sender},
        member_ids={sender},
    )
    chat_id = 3004
    user_id = 7301
    su = dict(sender_username=tg_user)
    failures = 0
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    machine.handle_message(make_text(chat_id, user_id, "Summary limits", **su))
    machine.handle_message(make_text(chat_id, user_id, "Description limits", **su))
    # single-file max (default from config is 10MB)
    msg = machine.handle_message(
        make_attachment(chat_id, user_id, "too-big.txt", 11 * 1024 * 1024, b"x", **su)
    )
    failures += _check("File vượt kích thước cho phép" in msg, "single file size limit")
    # max files (default 10)
    for i in range(10):
        machine.handle_message(make_attachment(chat_id, user_id, f"f{i}.txt", 1, b"x", **su))
    msg = machine.handle_message(make_attachment(chat_id, user_id, "overflow.txt", 1, b"x", **su))
    failures += _check("vượt quá số lượng file cho phép" in msg, "max files limit")
    return failures


def test_slash_huy_cancels_session() -> int:
    sender = "jira-user-7601"
    tg_user = "u7601"
    machine, _, _ = build_state_machine(user_mapping={tg_user: sender}, member_ids={sender})
    chat_id = 3007
    user_id = 7601
    su = dict(sender_username=tg_user)
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    failures = 0
    failures += _check((chat_id, user_id) in machine._sessions, "session active before /huy")  # noqa: SLF001
    msg = machine.handle_message(make_text(chat_id, user_id, "/huy", **su))
    failures += _check("Đã hủy giao việc" in msg, "/huy returns cancel template")
    failures += _check((chat_id, user_id) not in machine._sessions, "/huy clears session")  # noqa: SLF001
    msg_at = machine.handle_message(make_text(chat_id, user_id, "/huy@test_bot", **su))
    failures += _check("Đã hủy giao việc" in msg_at, "/huy@bot returns cancel template")
    return failures


def test_timeout() -> int:
    sender = "jira-user-7401"
    tg_user = "u7401"
    machine, _, _ = build_state_machine(user_mapping={tg_user: sender}, member_ids={sender})
    chat_id = 3005
    user_id = 7401
    su = dict(sender_username=tg_user)
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    # force timeout by mutating in-memory buffer timestamp
    session = machine._sessions[(chat_id, user_id)]  # noqa: SLF001
    session.updated_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    msg = machine.handle_message(make_text(chat_id, user_id, "abc", **su))
    return _check("Mình chưa hiểu yêu cầu" in msg, "timeout clears session and treats next message as new")


def test_jira_error_mapping() -> int:
    sender = "jira-user-7501"
    tg_user = "u7501"
    machine, _, _ = build_state_machine(
        user_mapping={tg_user: sender},
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
    su = dict(sender_username=tg_user)
    machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    machine.handle_message(make_text(chat_id, user_id, "Summary rate limit", **su))
    machine.handle_message(make_text(chat_id, user_id, "Description rate limit", **su))
    machine.handle_message(make_text(chat_id, user_id, "không", **su))
    machine.handle_message(make_text(chat_id, user_id, "không", **su))
    machine.handle_message(make_text(chat_id, user_id, "2", **su))
    msg = machine.handle_message(make_text(chat_id, user_id, "có", **su))
    return _check("Jira đang giới hạn tần suất" in msg, "jira error code mapping")


def main() -> int:
    failures = 0
    failures += test_unknown_intent()
    failures += test_invalid_due_days()
    failures += test_not_admin_assign()
    failures += test_attachment_limits()
    failures += test_slash_huy_cancels_session()
    failures += test_timeout()
    failures += test_jira_error_mapping()
    if failures:
        print(f"PHASE 3 NEGATIVE TEST FAILED with {failures} issue(s)")
        return 1
    print("PHASE 3 NEGATIVE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
