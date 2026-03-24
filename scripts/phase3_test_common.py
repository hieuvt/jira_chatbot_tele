"""Hàm dùng chung cho test state machine (Phase 3): FakeJiraClient, FakeUsersStore, build_state_machine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.errors import JiraClientError
from src.conversation.state_machine import (
    ConversationStateMachine,
    FileMeta,
    MessageInput,
    StateMachineConfig,
)
from src.conversation.templates import load_template_bundle
from src.jira.models import AttachmentMeta, IssueCreateRequest, SubtaskCreateRequest


def load_runtime_config(config_path: str = "config/config.json") -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    if not isinstance(config, dict):
        raise ValueError("config file must be a JSON object")
    return config


@dataclass
class FakeJiraClient:
    """Giả lập JiraClient cho test: membership/admin, create/upload, có thể base_url để message thành công có link."""

    member_ids: set[str]
    admin_ids: set[str]
    base_url: str = ""
    fail_on_create: JiraClientError | None = None
    fail_on_subtask: JiraClientError | None = None
    fail_on_upload: JiraClientError | None = None
    created_issue_requests: list[IssueCreateRequest] | None = None
    created_subtask_requests: list[SubtaskCreateRequest] | None = None
    uploaded_payloads: list[tuple[str, list[AttachmentMeta]]] | None = None

    def __post_init__(self) -> None:
        if self.created_issue_requests is None:
            self.created_issue_requests = []
        if self.created_subtask_requests is None:
            self.created_subtask_requests = []
        if self.uploaded_payloads is None:
            self.uploaded_payloads = []

    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        _ = project_key
        return jira_account_id in self.member_ids

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        _ = project_key
        return jira_account_id in self.admin_ids

    def create_issue(self, request_data: IssueCreateRequest) -> str:
        if self.fail_on_create:
            raise self.fail_on_create
        assert self.created_issue_requests is not None
        self.created_issue_requests.append(request_data)
        return "OM-999"

    def create_subtasks(self, request_data: SubtaskCreateRequest) -> list[str]:
        if self.fail_on_subtask:
            raise self.fail_on_subtask
        assert self.created_subtask_requests is not None
        self.created_subtask_requests.append(request_data)
        return [f"OM-SUB-{i + 1}" for i in range(len(request_data.checklist_items))]

    def upload_attachments(self, issue_key: str, files: list[AttachmentMeta]) -> list[str]:
        if self.fail_on_upload:
            raise self.fail_on_upload
        assert self.uploaded_payloads is not None
        self.uploaded_payloads.append((issue_key, files))
        return [f"ATT-{i + 1}" for i in range(len(files))]


class FakeUsersStore:
    """Bộ nhớ in-memory giả UsersStore (map telegram_id -> jira_id)."""

    def __init__(self, seed: dict[str, str] | None = None) -> None:
        self._data = seed.copy() if seed else {}

    def get_jira_account_id(self, telegram_account_id: str) -> str | None:
        value = self._data.get(telegram_account_id)
        if not value:
            return None
        return value

    def upsert_mapping(
        self,
        telegram_account_id: str,
        jira_account_id: str,
        *,
        user_name: str = "",
        telegram_display_name: str = "",
    ) -> bool:
        _ = (user_name, telegram_display_name)
        if telegram_account_id in self._data:
            return False
        self._data[telegram_account_id] = jira_account_id
        return True

    def dump(self) -> dict[str, str]:
        return self._data.copy()


def build_state_machine(
    *,
    config_path: str = "config/config.json",
    user_mapping: dict[str, str] | None = None,
    member_ids: set[str] | None = None,
    admin_ids: set[str] | None = None,
    jira_overrides: dict[str, JiraClientError | None] | None = None,
) -> tuple[ConversationStateMachine, FakeJiraClient, FakeUsersStore]:
    """Dựng state machine + fake Jira + fake store từ config/templates thật."""
    runtime = load_runtime_config(config_path)
    jira = runtime.get("jira", {})
    if not isinstance(jira, dict):
        raise ValueError("config.jira must be object")
    conversation = runtime.get("conversation", {}) if isinstance(runtime.get("conversation"), dict) else {}
    telegram = runtime.get("telegram", {}) if isinstance(runtime.get("telegram"), dict) else {}
    attachments = telegram.get("attachments", {}) if isinstance(telegram.get("attachments"), dict) else {}

    template_bundle = load_template_bundle(Path("config/templates.json"))

    fake_jira = FakeJiraClient(
        member_ids=member_ids or set(),
        admin_ids=admin_ids or set(),
        fail_on_create=(jira_overrides or {}).get("create"),
        fail_on_subtask=(jira_overrides or {}).get("subtask"),
        fail_on_upload=(jira_overrides or {}).get("upload"),
    )
    users_store = FakeUsersStore(seed=user_mapping)
    machine = ConversationStateMachine(
        jira_client=fake_jira,
        users_store=users_store,
        templates=template_bundle.bot_replies,
        intent_aliases=template_bundle.intent_aliases,
        config=StateMachineConfig(
            project_key=str(jira["project_key"]),
            issue_type_id=str(jira["issue_type_id"]),
            subtask_issue_type_id=str(jira["subtask_issue_type_id"]),
            timeout_minutes=int(conversation.get("timeout_minutes", 10)),
            attachment_max_files=int(attachments.get("max_files", 10)),
            attachment_max_total_bytes=20 * 1024 * 1024,
            attachment_max_bytes=int(jira.get("attachment_max_bytes", 10 * 1024 * 1024)),
        ),
    )
    return machine, fake_jira, users_store


def make_text(chat_id: int, user_id: int, text: str) -> MessageInput:
    """Tin chỉ có text."""
    return MessageInput(chat_id=chat_id, user_id=user_id, text=text)


def make_reply(chat_id: int, user_id: int, reply_to_user_id: int, text: str = "") -> MessageInput:
    """Tin reply (giao việc chọn assignee)."""
    return MessageInput(chat_id=chat_id, user_id=user_id, text=text, reply_to_user_id=reply_to_user_id)


def make_attachment(chat_id: int, user_id: int, filename: str, size: int, content: bytes) -> MessageInput:
    """Tin có một file đính kèm giả."""
    payload = FileMeta(
        filename=filename,
        size=size,
        telegram_file_id=f"fake-{filename}",
        telegram_file_unique_id=f"uniq-{filename}",
        kind="document",
        mime_type="text/plain",
        content_bytes=content,
    )
    return MessageInput(chat_id=chat_id, user_id=user_id, attachments=[payload], text=None)
