"""Smoke test state machine (không mạng): /giaochotoi, /vieccuatoi, /giaoviec, /baoxong.

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
from src.jira.models import JiraIssueRecord


def _check(condition: bool, label: str) -> int:
    if condition:
        print(f"[OK] {label}")
        return 0
    print(f"[FAIL] {label}")
    return 1


def run_assign_self_flow() -> int:
    print("[scenario] giaochotoi (assign self) full flow")
    failures = 0
    chat_id = 2001
    user_id = 5001
    sender_jira = "jira-user-5001"
    tg_sender = "u5001"
    machine, fake_jira, _ = build_state_machine(
        user_mapping={tg_sender: sender_jira},
        member_ids={sender_jira},
        admin_ids=set(),
    )
    su = dict(sender_username=tg_sender)

    msg = machine.handle_message(make_text(chat_id, user_id, "/giaochotoi", **su))
    failures += _check("Nhập tiêu đề công việc" in msg, "ask summary after intent")

    msg = machine.handle_message(make_text(chat_id, user_id, "Task smoke phase3", **su))
    failures += _check("Nhập mô tả công việc" in msg, "ask description")

    msg = machine.handle_message(make_text(chat_id, user_id, "Mô tả cho smoke test", **su))
    failures += _check("thêm file đính kèm" in msg, "ask attachments")

    msg = machine.handle_message(make_attachment(chat_id, user_id, "a.txt", 5, b"hello", **su))
    failures += _check("thêm file đính kèm" in msg, "accept first attachment")

    msg = machine.handle_message(make_text(chat_id, user_id, "xong", **su))
    failures += _check("thêm checklist" in msg, "go to checklist after xong")

    msg = machine.handle_message(make_text(chat_id, user_id, "line 1\nline 2", **su))
    failures += _check("thêm checklist" in msg, "append checklist lines")

    msg = machine.handle_message(make_text(chat_id, user_id, "xong", **su))
    failures += _check("số ngày cần hoàn thành" in msg, "ask due days")

    msg = machine.handle_message(make_text(chat_id, user_id, "3", **su))
    failures += _check("Xác nhận tạo công việc" in msg, "show confirm")

    msg = machine.handle_message(make_text(chat_id, user_id, "có", **su))
    failures += _check("Tạo công việc thành công: OM-999" in msg, "create succeeds")

    failures += _check(len(fake_jira.created_issue_requests or []) == 1, "create_issue called once")
    failures += _check(len(fake_jira.created_subtask_requests or []) == 1, "create_subtasks called once")
    failures += _check(len(fake_jira.uploaded_payloads or []) == 1, "upload_attachments called once")
    return failures


def run_vieccuatoi_report_flow() -> int:
    print("[scenario] vieccuatoi report (fake empty lists)")
    failures = 0
    chat_id = 2003
    user_id = 5003
    sender_jira = "jira-user-5003"
    tg_sender = "u5003"
    machine, _, _ = build_state_machine(
        user_mapping={tg_sender: sender_jira},
        member_ids={sender_jira},
        admin_ids=set(),
    )
    su = dict(sender_username=tg_sender)
    msg = machine.handle_message(make_text(chat_id, user_id, "/vieccuatoi", **su))
    failures += _check(msg.startswith("__HTML__:"), "vieccuatoi returns HTML prefix")
    failures += _check("Việc của bạn" in msg, "report header present")
    return failures


def run_mark_done_flow() -> int:
    print("[scenario] baoxong mark done")
    failures = 0
    chat_id = 2004
    user_id = 5004
    sender_jira = "jira-user-5004"
    tg_sender = "u5004"
    machine, fake_jira, _ = build_state_machine(
        user_mapping={tg_sender: sender_jira},
        member_ids={sender_jira},
        admin_ids=set(),
    )
    assert fake_jira.incomplete_for_assignee is not None
    fake_jira.incomplete_for_assignee = [
        JiraIssueRecord("OM-1", "Task one", None, "To Do", sender_jira, "new"),
    ]
    su = dict(sender_username=tg_sender)
    msg = machine.handle_message(make_text(chat_id, user_id, "/baoxong", **su))
    failures += _check(msg.startswith("__HTML__:"), "baoxong list uses HTML prefix")
    failures += _check("Nhập số thứ tự" in msg and "OM-1" in msg, "list incomplete tasks")
    msg = machine.handle_message(make_text(chat_id, user_id, "1", **su))
    failures += _check(msg.startswith("__HTML__:"), "baoxong confirm uses HTML prefix")
    failures += _check("OM-1" in msg and ("Có" in msg or "có" in msg.lower()), "confirm mark done")
    msg = machine.handle_message(make_text(chat_id, user_id, "có", **su))
    failures += _check(msg.startswith("__HTML__:"), "baoxong success uses HTML prefix")
    failures += _check("Đã cập nhật trạng thái" in msg and "OM-1" in msg, "transition success message")
    failures += _check(fake_jira.transitioned_to_done == ["OM-1"], "transition_issue_to_done called once")
    return failures


def run_assign_task_flow() -> int:
    print("[scenario] assign_task with missing assignee mapping")
    failures = 0
    chat_id = 2002
    sender_tg = 6001
    assignee_tg = 6002
    sender_jira = "jira-admin-6001"
    assignee_jira = "jira-user-6002"
    tg_sender = "u6001"
    tg_assignee = "assignee6002"
    machine, fake_jira, users = build_state_machine(
        user_mapping={tg_sender: sender_jira},
        member_ids={sender_jira, assignee_jira},
        admin_ids={sender_jira},
    )
    su_admin = dict(sender_username=tg_sender)

    msg = machine.handle_message(make_text(chat_id, sender_tg, "/giaoviec", **su_admin))
    failures += _check("Chọn người được giao việc" in msg, "ask assignee")

    msg = machine.handle_message(
        make_reply(
            chat_id,
            sender_tg,
            assignee_tg,
            text="",
            reply_to_username=tg_assignee,
            sender_username=tg_sender,
        )
    )
    failures += _check("Người này chưa liên kết Jira" in msg, "ask assignee jira id")

    msg = machine.handle_message(make_text(chat_id, sender_tg, assignee_jira, **su_admin))
    failures += _check("Nhập tiêu đề công việc" in msg, "go to summary after assignee id")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "Assign task summary", **su_admin))
    failures += _check("Nhập mô tả công việc" in msg, "ask description assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "Assign task description", **su_admin))
    failures += _check("thêm file đính kèm" in msg, "ask attachments assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "không", **su_admin))
    failures += _check("thêm checklist" in msg, "skip attachments")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "không", **su_admin))
    failures += _check("số ngày cần hoàn thành" in msg, "skip checklist")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "2", **su_admin))
    failures += _check("Xác nhận tạo công việc" in msg, "confirm assign flow")

    msg = machine.handle_message(make_text(chat_id, sender_tg, "yes", **su_admin))
    failures += _check("Tạo công việc thành công: OM-999" in msg, "create assign flow success")

    users_data = users.dump()
    failures += _check(users_data.get(tg_assignee) == assignee_jira, "assignee mapping upserted")
    failures += _check(len(fake_jira.created_issue_requests or []) == 1, "issue created once assign flow")
    return failures


def main() -> int:
    failures = 0
    failures += run_assign_self_flow()
    failures += run_vieccuatoi_report_flow()
    failures += run_mark_done_flow()
    failures += run_assign_task_flow()
    if failures:
        print(f"PHASE 3 SMOKE TEST FAILED with {failures} issue(s)")
        return 1
    print("PHASE 3 SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
