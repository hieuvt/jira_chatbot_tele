"""Phase 3 smoke tests for Telegram conversation state machine.

Usage:
  python scripts/phase3_smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from phase3_test_common import build_state_machine, make_attachment, make_reply, make_text


def _check(condition: bool, label: str) -> int:
    if condition:
        print(f"[OK] {label}")
        return 0
    print(f"[FAIL] {label}")
    return 1


def run_my_task_flow() -> int:
    print("[scenario] my_task full flow")
    failures = 0
    chat_id = 2001
    user_id = 5001
    sender_jira = "jira-user-5001"
    machine, fake_jira, _ = build_state_machine(
        user_mapping={str(user_id): sender_jira},
        member_ids={sender_jira},
        admin_ids=set(),
    )

    msg = machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi"))
    failures += _check("Nhập tiêu đề công việc" in msg, "ask summary after intent")

    msg = machine.handle_message(make_text(chat_id, user_id, "Task smoke phase3"))
    failures += _check("Nhập mô tả công việc" in msg, "ask description")

    msg = machine.handle_message(make_text(chat_id, user_id, "Mô tả cho smoke test"))
    failures += _check("thêm file đính kèm" in msg, "ask attachments")

    msg = machine.handle_message(make_attachment(chat_id, user_id, "a.txt", 5, b"hello"))
    failures += _check("thêm file đính kèm" in msg, "accept first attachment")

    msg = machine.handle_message(make_text(chat_id, user_id, "xong"))
    failures += _check("thêm checklist" in msg, "go to checklist after xong")

    msg = machine.handle_message(make_text(chat_id, user_id, "line 1\nline 2"))
    failures += _check("thêm checklist" in msg, "append checklist lines")

    msg = machine.handle_message(make_text(chat_id, user_id, "xong"))
    failures += _check("số ngày cần hoàn thành" in msg, "ask due days")

    msg = machine.handle_message(make_text(chat_id, user_id, "3"))
    failures += _check("Xác nhận tạo công việc" in msg, "show confirm")

    msg = machine.handle_message(make_text(chat_id, user_id, "có"))
    failures += _check("Tạo công việc thành công: OM-999" in msg, "create succeeds")

    failures += _check(len(fake_jira.created_issue_requests or []) == 1, "create_issue called once")
    failures += _check(len(fake_jira.created_subtask_requests or []) == 1, "create_subtasks called once")
    failures += _check(len(fake_jira.uploaded_payloads or []) == 1, "upload_attachments called once")
    return failures


def run_assign_task_flow() -> int:
    print("[scenario] assign_task with missing assignee mapping")
    failures = 0
    chat_id = 2002
    sender_tg = 6001
    assignee_tg = 6002
    sender_jira = "jira-admin-6001"
    assignee_jira = "jira-user-6002"
    machine, fake_jira, users = build_state_machine(
        user_mapping={str(sender_tg): sender_jira},
        member_ids={sender_jira, assignee_jira},
        admin_ids={sender_jira},
    )

    msg = machine.handle_message(make_text(chat_id, sender_tg, "/giaoviec"))
    failures += _check("Chọn người được giao việc" in msg, "ask assignee")

    msg = machine.handle_message(make_reply(chat_id, sender_tg, assignee_tg, text=""))
    failures += _check("Người này chưa liên kết Jira" in msg, "ask assignee jira id")

    msg = machine.handle_message(make_text(chat_id, sender_tg, assignee_jira))
    failures += _check("Nhập tiêu đề công việc" in msg, "go to summary after assignee id")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "Assign task summary"))
    failures += _check("Nhập mô tả công việc" in msg, "ask description assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "Assign task description"))
    failures += _check("thêm file đính kèm" in msg, "ask attachments assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "không"))
    failures += _check("thêm checklist" in msg, "skip attachments")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "không"))
    failures += _check("số ngày cần hoàn thành" in msg, "skip checklist")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "2"))
    failures += _check("Xác nhận tạo công việc" in msg, "confirm assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "yes"))
    failures += _check("Tạo công việc thành công: OM-999" in msg, "create assign flow success")

    users_data = users.dump()
    failures += _check(users_data.get(str(assignee_tg)) == assignee_jira, "assignee mapping upserted")
    failures += _check(len(fake_jira.created_issue_requests or []) == 1, "issue created once assign flow")
    return failures


def main() -> int:
    failures = 0
    failures += run_my_task_flow()
    failures += run_assign_task_flow()
    if failures:
        print(f"PHASE 3 SMOKE TEST FAILED with {failures} issue(s)")
        return 1
    print("PHASE 3 SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
