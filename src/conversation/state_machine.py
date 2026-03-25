"""
Máy trạng thái hội thoại Telegram (Phase 3): /giaoviec, /vieccuatoi, buffer theo (chat_id, user_id),
gọi JiraClient + UsersStore, trả về text từ templates.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Chạy trực tiếp file này chỉ thêm `src/conversation` vào sys.path — cần thêm root repo để import `src.*`
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from src.common.errors import JiraClientError
from src.conversation.intents import Intent, resolve_intent
from src.conversation.validators import (
    is_co,
    is_huy,
    is_khong,
    is_xong,
    parse_due_days,
    split_checklist_lines,
)
from src.jira.models import AttachmentMeta, IssueCreateRequest, SubtaskCreateRequest


# --- Các trạng thái FSM (bước hỏi / kiểm tra Jira) ---


class ConversationState(str, Enum):
    S0_START_ASSIGN = "S0_START_ASSIGN"
    S0_START_MY_TASK = "S0_START_MY_TASK"
    S1_ASK_SENDER_JIRA_ID = "S1_ASK_SENDER_JIRA_ID"
    S2_CHECK_SENDER_MEMBER = "S2_CHECK_SENDER_MEMBER"
    S3_CHECK_SENDER_ADMIN = "S3_CHECK_SENDER_ADMIN"
    S4_ASK_ASSIGNEE = "S4_ASK_ASSIGNEE"
    S5_CHECK_ASSIGNEE_MEMBER = "S5_CHECK_ASSIGNEE_MEMBER"
    S6_ASK_SUMMARY = "S6_ASK_SUMMARY"
    S7_ASK_DESCRIPTION = "S7_ASK_DESCRIPTION"
    S8_ASK_ATTACHMENTS = "S8_ASK_ATTACHMENTS"
    S9_ASK_CHECKLIST = "S9_ASK_CHECKLIST"
    S10_ASK_DUE_DAYS = "S10_ASK_DUE_DAYS"
    S11_CONFIRM = "S11_CONFIRM"
    S12_CREATE = "S12_CREATE"


@dataclass
class FileMeta:
    """Metadata file tải từ Telegram (kèm bytes) trước khi upload Jira."""
    filename: str
    size: int
    telegram_file_id: str
    telegram_file_unique_id: str | None
    kind: str
    mime_type: str | None
    content_bytes: bytes


@dataclass
class MessageInput:
    """Một tin vào state machine: text, reply/mention, media."""
    chat_id: int
    user_id: int
    text: str | None = None
    reply_to_user_id: int | None = None
    reply_to_username: str | None = None  # lowercase, không @ — khớp users.json
    mentioned_user_id: int | None = None
    mentioned_username: str | None = None  # lowercase — khớp users.json
    sender_username: str | None = None  # @username Telegram chuẩn hoá; None = không persist/tra store
    sender_user_name: str | None = None
    sender_telegram_display_name: str | None = None
    reply_target_user_name: str | None = None
    reply_target_telegram_display_name: str | None = None
    mentioned_user_name: str | None = None
    mentioned_telegram_display_name: str | None = None
    attachments: list[FileMeta] = field(default_factory=list)

    @property
    def has_media(self) -> bool:
        return bool(self.attachments)


@dataclass
class ConversationBuffer:
    """Trạng thái phiên làm việc của một user trong một chat."""
    intent: Intent
    chat_id: int
    user_id: int
    state: ConversationState
    sender_jira_account_id: str | None = None
    assignee_jira_account_id: str | None = None
    assignee_telegram_display: str | None = None
    sender_username: str | None = None
    pending_assignee_awaiting_jira: bool = False
    pending_assignee_username: str | None = None  # để upsert sau khi nhập jira (username-only store)
    pending_assignee_telegram_user_id: int | None = None
    pending_assignee_telegram_display: str | None = None
    pending_assignee_telegram_display_name: str | None = None
    summary: str | None = None
    description: str | None = None
    checklist_items: list[str] = field(default_factory=list)
    due_days: int | None = None
    attachments: list[FileMeta] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def clear_attachments(self) -> None:
        for item in self.attachments:
            item.content_bytes = b""
        self.attachments.clear()


@dataclass
class StateMachineConfig:
    """Tham số cố định từ config: project, loại issue, giới hạn file."""
    project_key: str
    issue_type_id: str
    subtask_issue_type_id: str
    timeout_minutes: int = 10
    attachment_max_files: int = 10
    attachment_max_total_bytes: int = 20 * 1024 * 1024
    attachment_max_bytes: int | None = None


class ConversationStateMachine:
    """Điều phối intent, session timeout, và từng bước nhập liệu tới khi tạo issue Jira."""

    def __init__(
        self,
        *,
        jira_client: object,
        users_store: object,
        templates: dict[str, str],
        config: StateMachineConfig,
        intent_aliases: dict[str, list[str]] | None = None,
    ) -> None:
        self._jira_client = jira_client
        self._users_store = users_store
        self._templates = templates
        self._config = config
        self._intent_aliases = intent_aliases or {}
        self._sessions: dict[tuple[int, int], ConversationBuffer] = {}

    def handle_message(self, message: MessageInput) -> str:
        """Điểm vào chính: hủy, intent mới, tiếp tục phiên hoặc unknown."""
        key = (message.chat_id, message.user_id)
        existing = self._sessions.get(key)
        if existing and self._is_expired(existing):
            self._end_session(key)
            existing = None

        if message.text and is_huy(message.text):
            self._end_session(key)
            return self._tpl("TPL_CANCELLED")

        if existing:
            route = resolve_intent(message.text or "", intent_aliases=self._intent_aliases)
            if route.intent in {Intent.ASSIGN_TASK, Intent.MY_TASK}:
                self._end_session(key)
                return self._start_new_session(message=message, intent=route.intent)
            existing.touch()
            return self._handle_existing(buffer=existing, message=message, key=key)

        route = resolve_intent(message.text or "", intent_aliases=self._intent_aliases)
        if route.intent == Intent.UNKNOWN:
            return self._tpl("TPL_UNKNOWN_INTENT")
        return self._start_new_session(message=message, intent=route.intent)

    def _start_new_session(self, *, message: MessageInput, intent: Intent) -> str:
        """Tạo buffer mới và chạy các bước không cần input tới khi phải hỏi user."""
        if intent == Intent.ASSIGN_TASK:
            buffer = ConversationBuffer(
                intent=intent,
                chat_id=message.chat_id,
                user_id=message.user_id,
                state=ConversationState.S0_START_ASSIGN,
                sender_username=message.sender_username,
            )
        else:
            buffer = ConversationBuffer(
                intent=intent,
                chat_id=message.chat_id,
                user_id=message.user_id,
                state=ConversationState.S0_START_MY_TASK,
                sender_username=message.sender_username,
            )
        key = (message.chat_id, message.user_id)
        self._sessions[key] = buffer
        return self._run_non_interactive_states(buffer=buffer, key=key)

    def _handle_existing(self, *, buffer: ConversationBuffer, message: MessageInput, key: tuple[int, int]) -> str:
        """Phân nhánh theo `buffer.state` cho tin trong phiên đang mở."""
        if buffer.state == ConversationState.S1_ASK_SENDER_JIRA_ID:
            return self._on_sender_id(buffer=buffer, message=message, key=key)
        if buffer.state == ConversationState.S4_ASK_ASSIGNEE:
            return self._on_assignee(buffer=buffer, message=message, key=key)
        if buffer.state == ConversationState.S6_ASK_SUMMARY:
            return self._on_summary(buffer=buffer, message=message)
        if buffer.state == ConversationState.S7_ASK_DESCRIPTION:
            return self._on_description(buffer=buffer, message=message)
        if buffer.state == ConversationState.S8_ASK_ATTACHMENTS:
            return self._on_attachments(buffer=buffer, message=message)
        if buffer.state == ConversationState.S9_ASK_CHECKLIST:
            return self._on_checklist(buffer=buffer, message=message)
        if buffer.state == ConversationState.S10_ASK_DUE_DAYS:
            return self._on_due_days(buffer=buffer, message=message)
        if buffer.state == ConversationState.S11_CONFIRM:
            return self._on_confirm(buffer=buffer, message=message, key=key)
        return self._tpl("TPL_UNKNOWN_INTENT")

    def _run_non_interactive_states(self, *, buffer: ConversationBuffer, key: tuple[int, int]) -> str:
        """Vòng lặp: kiểm tra mapping, member Jira, admin (giao việc), assignee — tới bước cần hỏi hoặc tạo issue."""
        while True:
            if buffer.state in {ConversationState.S0_START_ASSIGN, ConversationState.S0_START_MY_TASK}:
                sender = (
                    self._users_store.get_jira_account_id(buffer.sender_username)
                    if buffer.sender_username
                    else None
                )
                if sender:
                    buffer.sender_jira_account_id = sender
                    buffer.state = ConversationState.S2_CHECK_SENDER_MEMBER
                    continue
                buffer.state = ConversationState.S1_ASK_SENDER_JIRA_ID
                return self._tpl("TPL_ASK_SENDER_JIRA_ID")

            if buffer.state == ConversationState.S2_CHECK_SENDER_MEMBER:
                assert buffer.sender_jira_account_id
                try:
                    is_member = self._jira_client.check_project_membership(
                        buffer.sender_jira_account_id, self._config.project_key
                    )
                except JiraClientError as exc:
                    self._end_session(key)
                    return self._map_jira_error(exc)
                if not is_member:
                    self._end_session(key)
                    return self._tpl("TPL_NOT_PROJECT_MEMBER")
                if buffer.intent == Intent.MY_TASK:
                    buffer.assignee_jira_account_id = buffer.sender_jira_account_id
                    buffer.state = ConversationState.S6_ASK_SUMMARY
                    return self._tpl("TPL_ASK_SUMMARY")
                buffer.state = ConversationState.S3_CHECK_SENDER_ADMIN
                continue

            if buffer.state == ConversationState.S3_CHECK_SENDER_ADMIN:
                assert buffer.sender_jira_account_id
                try:
                    is_admin = self._jira_client.check_project_admin(
                        buffer.sender_jira_account_id, self._config.project_key
                    )
                except JiraClientError as exc:
                    self._end_session(key)
                    return self._map_jira_error(exc)
                if not is_admin:
                    self._end_session(key)
                    return self._tpl("TPL_NOT_ADMIN_ASSIGN")
                buffer.state = ConversationState.S4_ASK_ASSIGNEE
                return (
                    "Chọn người được giao việc: reply tin nhắn của họ hoặc @mention họ. "
                    "Nếu không, bạn có thể nhập trực tiếp jira_account_id."
                )

            if buffer.state == ConversationState.S5_CHECK_ASSIGNEE_MEMBER:
                assert buffer.assignee_jira_account_id
                try:
                    is_member = self._jira_client.check_project_membership(
                        buffer.assignee_jira_account_id, self._config.project_key
                    )
                except JiraClientError as exc:
                    self._end_session(key)
                    return self._map_jira_error(exc)
                if not is_member:
                    self._end_session(key)
                    return self._tpl("TPL_ASSIGNEE_NOT_MEMBER")
                buffer.state = ConversationState.S6_ASK_SUMMARY
                return self._tpl("TPL_ASK_SUMMARY")

            if buffer.state == ConversationState.S12_CREATE:
                return self._create_jira_issue(buffer=buffer, key=key)

            return self._tpl("TPL_UNKNOWN_INTENT")

    # --- Xử lý từng bước nhập liệu ---

    def _on_sender_id(self, *, buffer: ConversationBuffer, message: MessageInput, key: tuple[int, int]) -> str:
        """User gửi jira_account_id khi chưa có mapping; upsert rồi kiểm tra member."""
        if message.has_media or not message.text or not message.text.strip():
            return self._tpl("TPL_ASK_SENDER_JIRA_ID")
        jira_account_id = message.text.strip()
        if message.sender_username:
            self._users_store.upsert_mapping(
                message.sender_username,
                jira_account_id,
                telegram_display_name=message.sender_telegram_display_name or "",
            )
        buffer.sender_jira_account_id = jira_account_id
        buffer.state = ConversationState.S2_CHECK_SENDER_MEMBER
        return self._run_non_interactive_states(buffer=buffer, key=key)

    def _on_assignee(self, *, buffer: ConversationBuffer, message: MessageInput, key: tuple[int, int]) -> str:
        """Chọn người được giao: reply, @mention, hoặc nhập jira_account_id; có thể hỏi thêm jira id."""
        def _to_telegram_display(*, username: str | None, user_id: int | None) -> str:
            if isinstance(username, str) and username.strip():
                normalized = username.strip().lstrip("@")
                return f"@{normalized}"
            if user_id is None:
                return ""
            return str(user_id)

        def _clear_pending_assignee(buffer: ConversationBuffer) -> None:
            buffer.pending_assignee_awaiting_jira = False
            buffer.pending_assignee_username = None
            buffer.pending_assignee_telegram_user_id = None
            buffer.pending_assignee_telegram_display = None
            buffer.pending_assignee_telegram_display_name = None

        if buffer.pending_assignee_awaiting_jira and message.text and message.text.strip() and not message.has_media:
            pending_display = buffer.pending_assignee_telegram_display
            pending_uid = buffer.pending_assignee_telegram_user_id
            jira_account_id = message.text.strip()
            if buffer.pending_assignee_username or buffer.pending_assignee_telegram_display_name:
                self._users_store.upsert_mapping(
                    buffer.pending_assignee_username or buffer.pending_assignee_telegram_display_name,
                    jira_account_id,
                    telegram_display_name=buffer.pending_assignee_telegram_display_name or "",
                )
            _clear_pending_assignee(buffer)
            buffer.assignee_telegram_display = pending_display or (str(pending_uid) if pending_uid else None)
            buffer.assignee_jira_account_id = jira_account_id
            buffer.state = ConversationState.S5_CHECK_ASSIGNEE_MEMBER
            return self._run_non_interactive_states(buffer=buffer, key=key)

        if message.mentioned_username:
            mapped = self._users_store.get_jira_account_id(message.mentioned_username)
            if mapped:
                buffer.assignee_jira_account_id = mapped
                buffer.assignee_telegram_display = _to_telegram_display(
                    username=message.mentioned_username,
                    user_id=message.mentioned_user_id,
                )
                buffer.state = ConversationState.S5_CHECK_ASSIGNEE_MEMBER
                return self._run_non_interactive_states(buffer=buffer, key=key)
            buffer.pending_assignee_awaiting_jira = True
            buffer.pending_assignee_username = message.mentioned_username
            buffer.pending_assignee_telegram_user_id = message.mentioned_user_id
            buffer.pending_assignee_telegram_display = _to_telegram_display(
                username=message.mentioned_username,
                user_id=message.mentioned_user_id,
            )
            buffer.pending_assignee_telegram_display_name = message.mentioned_telegram_display_name or ""
            return self._tpl("TPL_ASK_ASSIGNEE")

        if message.mentioned_user_id:
            buffer.pending_assignee_awaiting_jira = True
            buffer.pending_assignee_username = None
            buffer.pending_assignee_telegram_user_id = message.mentioned_user_id
            buffer.pending_assignee_telegram_display = _to_telegram_display(
                username=message.mentioned_user_name,
                user_id=message.mentioned_user_id,
            )
            buffer.pending_assignee_telegram_display_name = message.mentioned_telegram_display_name or ""
            return self._tpl("TPL_ASK_ASSIGNEE")

        # Reply tin nhắn của assignee (ForceReply trong nhóm)
        if message.reply_to_username:
            mapped = self._users_store.get_jira_account_id(message.reply_to_username)
            if mapped:
                buffer.assignee_jira_account_id = mapped
                buffer.assignee_telegram_display = _to_telegram_display(
                    username=message.reply_to_username,
                    user_id=message.reply_to_user_id,
                )
                buffer.state = ConversationState.S5_CHECK_ASSIGNEE_MEMBER
                return self._run_non_interactive_states(buffer=buffer, key=key)
            buffer.pending_assignee_awaiting_jira = True
            buffer.pending_assignee_username = message.reply_to_username
            buffer.pending_assignee_telegram_user_id = message.reply_to_user_id
            buffer.pending_assignee_telegram_display = _to_telegram_display(
                username=message.reply_to_username,
                user_id=message.reply_to_user_id,
            )
            buffer.pending_assignee_telegram_display_name = message.reply_target_telegram_display_name or ""
            return self._tpl("TPL_ASK_ASSIGNEE")

        if message.reply_to_user_id:
            buffer.pending_assignee_awaiting_jira = True
            buffer.pending_assignee_username = None
            buffer.pending_assignee_telegram_user_id = message.reply_to_user_id
            buffer.pending_assignee_telegram_display = _to_telegram_display(
                username=message.reply_to_username,
                user_id=message.reply_to_user_id,
            )
            buffer.pending_assignee_telegram_display_name = message.reply_target_telegram_display_name or ""
            return self._tpl("TPL_ASK_ASSIGNEE")

        if message.has_media or not message.text or not message.text.strip():
            return (
                "Chọn người được giao việc: reply tin nhắn của họ hoặc @mention họ. "
                "Nếu không, bạn có thể nhập trực tiếp jira_account_id."
            )
        jira_account_id = message.text.strip()
        if buffer.pending_assignee_awaiting_jira:
            pending_display = buffer.pending_assignee_telegram_display
            pending_uid = buffer.pending_assignee_telegram_user_id
            if buffer.pending_assignee_username:
                self._users_store.upsert_mapping(
                    buffer.pending_assignee_username,
                    jira_account_id,
                    telegram_display_name=buffer.pending_assignee_telegram_display_name or "",
                )
            _clear_pending_assignee(buffer)
            buffer.assignee_telegram_display = pending_display or (str(pending_uid) if pending_uid else None)
        else:
            # User nhập trực tiếp `jira_account_id` (không có mention/reply), nên giữ hiển thị theo jira.
            buffer.assignee_telegram_display = None
        buffer.assignee_jira_account_id = jira_account_id
        buffer.state = ConversationState.S5_CHECK_ASSIGNEE_MEMBER
        return self._run_non_interactive_states(buffer=buffer, key=key)

    def _on_summary(self, *, buffer: ConversationBuffer, message: MessageInput) -> str:
        """Nhập tiêu đề issue (cắt 255 ký tự)."""
        if message.has_media or not message.text or not message.text.strip():
            return self._tpl("TPL_ASK_SUMMARY")
        summary = message.text.strip()
        if len(summary) > 255:
            summary = summary[:255]
        buffer.summary = summary
        buffer.state = ConversationState.S7_ASK_DESCRIPTION
        return self._tpl("TPL_ASK_DESCRIPTION")

    def _on_description(self, *, buffer: ConversationBuffer, message: MessageInput) -> str:
        """Nhập mô tả (description) issue."""
        if message.has_media or not message.text or not message.text.strip():
            return self._tpl("TPL_ASK_DESCRIPTION")
        buffer.description = message.text.strip()
        buffer.state = ConversationState.S8_ASK_ATTACHMENTS
        return self._tpl("TPL_ASK_ATTACHMENTS")

    def _on_attachments(self, *, buffer: ConversationBuffer, message: MessageInput) -> str:
        """Upload file hoặc Không / Xong; kiểm tra số file và dung lượng."""
        if message.has_media:
            if len(buffer.attachments) + len(message.attachments) > self._config.attachment_max_files:
                return "Đã vượt quá số lượng file cho phép. Vui lòng giảm số file gửi."
            current_size = sum(item.size for item in buffer.attachments)
            for incoming in message.attachments:
                if self._config.attachment_max_bytes and incoming.size > self._config.attachment_max_bytes:
                    return "File vượt kích thước cho phép. Vui lòng gửi file nhỏ hơn."
                if current_size + incoming.size > self._config.attachment_max_total_bytes:
                    return "Tổng dung lượng file của phiên đã vượt 20MB. Vui lòng gửi file nhỏ hơn hoặc bớt file."
                buffer.attachments.append(incoming)
                current_size += incoming.size
            return self._tpl("TPL_ASK_ATTACHMENTS")

        if not message.text:
            return self._tpl("TPL_ASK_ATTACHMENTS")
        if is_khong(message.text):
            buffer.state = ConversationState.S9_ASK_CHECKLIST
            return self._tpl("TPL_ASK_CHECKLIST")
        if is_xong(message.text):
            if not buffer.attachments:
                return self._tpl("TPL_ASK_ATTACHMENTS")
            buffer.state = ConversationState.S9_ASK_CHECKLIST
            return self._tpl("TPL_ASK_CHECKLIST")
        return self._tpl("TPL_ASK_ATTACHMENTS")

    def _on_checklist(self, *, buffer: ConversationBuffer, message: MessageInput) -> str:
        """Nhập checklist theo dòng; tối đa 20 mục."""
        if message.has_media or not message.text:
            return self._tpl("TPL_ASK_CHECKLIST")
        if is_khong(message.text) and not buffer.checklist_items:
            buffer.state = ConversationState.S10_ASK_DUE_DAYS
            return self._tpl("TPL_ASK_DUE_DAYS")
        if is_xong(message.text):
            buffer.state = ConversationState.S10_ASK_DUE_DAYS
            return self._tpl("TPL_ASK_DUE_DAYS")
        items = split_checklist_lines(message.text)
        if not items:
            return self._tpl("TPL_ASK_CHECKLIST")
        if len(buffer.checklist_items) + len(items) > 20:
            return "Checklist tối đa 20 mục. Vui lòng nhập ít hơn."
        buffer.checklist_items.extend(items)
        return self._tpl("TPL_ASK_CHECKLIST")

    def _on_due_days(self, *, buffer: ConversationBuffer, message: MessageInput) -> str:
        """Số ngày hoàn thành (due = now UTC + N ngày khi tạo issue)."""
        if message.has_media or not message.text:
            return self._tpl("TPL_INVALID_DUE_DAYS")
        try:
            buffer.due_days = parse_due_days(message.text)
        except ValueError:
            return self._tpl("TPL_INVALID_DUE_DAYS")
        buffer.state = ConversationState.S11_CONFIRM
        return self._render_confirm(buffer)

    def _on_confirm(self, *, buffer: ConversationBuffer, message: MessageInput, key: tuple[int, int]) -> str:
        """Có -> chuyển S12_CREATE; Không -> hủy phiên."""
        if message.has_media or not message.text:
            return self._tpl("TPL_INVALID_CONFIRM")
        if is_co(message.text):
            buffer.state = ConversationState.S12_CREATE
            return self._run_non_interactive_states(buffer=buffer, key=key)
        if is_khong(message.text):
            self._end_session(key)
            return self._tpl("TPL_CANCELLED")
        return self._tpl("TPL_INVALID_CONFIRM")

    def _create_jira_issue(self, *, buffer: ConversationBuffer, key: tuple[int, int]) -> str:
        """Gọi Jira: issue chính, sub-task checklist, upload file; kết thúc phiên."""
        assert buffer.summary and buffer.description and buffer.assignee_jira_account_id and buffer.due_days
        due_date = (datetime.now(timezone.utc) + timedelta(days=buffer.due_days)).strftime("%Y-%m-%d")
        try:
            issue_key = self._jira_client.create_issue(
                IssueCreateRequest(
                    project_key=self._config.project_key,
                    summary=buffer.summary,
                    description=buffer.description,
                    assignee_account_id=buffer.assignee_jira_account_id,
                    due_date=due_date,
                    issue_type_id=self._config.issue_type_id,
                )
            )
            subtask_keys: list[str] = []
            if buffer.checklist_items:
                subtask_keys = self._jira_client.create_subtasks(
                    SubtaskCreateRequest(
                        parent_issue_key=issue_key,
                        issue_type_id=self._config.subtask_issue_type_id,
                        checklist_items=buffer.checklist_items,
                    )
                )
            uploaded_ids: list[str] = []
            if buffer.attachments:
                uploaded_ids = self._jira_client.upload_attachments(
                    issue_key=issue_key,
                    files=[
                        AttachmentMeta(
                            filename=att.filename,
                            size_bytes=att.size,
                            telegram_file_id=att.telegram_file_id,
                            content_bytes=att.content_bytes,
                            content_type=att.mime_type or "application/octet-stream",
                        )
                        for att in buffer.attachments
                    ],
                )
            self._end_session(key)
            # Telegram tự động biến URL thành link click được.
            issue_url = f"{self._jira_client.base_url}/browse/{issue_key}" if getattr(self._jira_client, "base_url", None) else None
            return (
                f"Tạo công việc thành công: {issue_key}\n"
                f"{f'Link Jira: {issue_url}\n' if issue_url else ''}"
                f"Số checklist items: {len(subtask_keys)}\n"
                f"Số file upload: {len(uploaded_ids)}"
            )
        except JiraClientError as exc:
            self._end_session(key)
            return self._map_jira_error(exc)

    def _render_confirm(self, buffer: ConversationBuffer) -> str:
        """Ghép bản tóm tắt + template xác nhận."""
        description = (buffer.description or "").strip()
        if len(description) > 500:
            description = f"{description[:500]}..."
        summary = buffer.summary or ""
        assignee = buffer.assignee_telegram_display or buffer.assignee_jira_account_id or ""
        due_days = buffer.due_days or 0
        info = (
            f"Assignee: {assignee}\n"
            f"Summary: {summary}\n"
            f"Description: {description}\n"
            f"Checklist items: {len(buffer.checklist_items)}\n"
            f"Attachments: {len(buffer.attachments)}\n"
            f"Due days: {due_days}\n"
        )
        return f"{info}{self._tpl('TPL_CONFIRM_CREATE')}"

    def _map_jira_error(self, error: JiraClientError) -> str:
        """Ánh xạ mã lỗi JiraClient sang câu tiếng Việt cho user."""
        if error.code == "JIRA_PERMISSION_DENIED":
            return (
                "Bot chưa đủ quyền kiểm tra project trên Jira (Browse/Admin project). "
                "Vui lòng liên hệ quản trị viên cấp quyền cho tài khoản bot."
            )
        if error.code == "JIRA_NETWORK_ERROR":
            return "Không kết nối được Jira. Vui lòng thử lại sau."
        if error.code == "JIRA_AUTH_OR_PERMISSION":
            return "Bot chưa đủ quyền thao tác trên Jira. Vui lòng liên hệ quản trị viên."
        if error.code in {"JIRA_BAD_REQUEST", "JIRA_INVALID_DUE_DATE"}:
            return "Dữ liệu chưa hợp lệ để tạo việc. Vui lòng kiểm tra lại thông tin đã nhập."
        if error.code == "JIRA_RATE_LIMITED" and error.retriable:
            return "Jira đang giới hạn tần suất. Vui lòng thử lại sau ít phút."
        if error.code == "JIRA_NOT_FOUND":
            return "Cấu hình Jira chưa đúng hoặc tài nguyên không tồn tại. Vui lòng báo quản trị viên kiểm tra project/issue type."
        if error.code in {"JIRA_SERVER_ERROR", "JIRA_HTTP_ERROR", "JIRA_INVALID_JSON", "JIRA_UNKNOWN_ERROR"}:
            return "Đã có lỗi khi tạo công việc trên Jira. Vui lòng thử lại sau."
        return "Đã có lỗi khi tạo công việc trên Jira. Vui lòng thử lại sau."

    def _end_session(self, key: tuple[int, int]) -> None:
        """Xóa session và giải phóng bytes file đính kèm trong buffer."""
        existing = self._sessions.pop(key, None)
        if existing:
            existing.clear_attachments()

    def _is_expired(self, buffer: ConversationBuffer) -> bool:
        """Quá `timeout_minutes` kể từ lần cập nhật cuối."""
        return datetime.now(timezone.utc) - buffer.updated_at > timedelta(minutes=self._config.timeout_minutes)

    def _tpl(self, key: str) -> str:
        """Lấy câu trả lời theo key TPL_*; thiếu key thì trả về chính key."""
        return self._templates.get(key, key)


def build_filename(kind: str, mime_type: str | None, timestamp: int) -> str:
    """Tên file fallback khi Telegram không gửi file_name (theo loại media + mime)."""
    ext = ".bin"
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            ext = guessed
    return f"{kind}_{timestamp}{ext}"

