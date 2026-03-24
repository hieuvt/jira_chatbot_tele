"""DTO (dataclass) mô tả payload/record khi gọi Jira Cloud REST API."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IssueCreateRequest:
    """Yêu cầu tạo issue chính (task) trên Jira."""

    project_key: str
    summary: str
    description: str
    assignee_account_id: str
    due_date: str
    issue_type_id: str


@dataclass
class AttachmentMeta:
    """Một file đính kèm chuẩn bị upload lên issue Jira."""

    filename: str
    size_bytes: int
    telegram_file_id: str
    content_bytes: bytes
    content_type: str = "application/octet-stream"


@dataclass
class SubtaskCreateRequest:
    """Tạo nhiều sub-task từ checklist; parent là issue chính."""

    parent_issue_key: str
    issue_type_id: str
    checklist_items: list[str] = field(default_factory=list)


@dataclass
class QueryIssuesRequest:
    """Tham số tìm issue theo due date (dùng cho reporter / client)."""

    project_key: str
    reporter_account_id: str  # Giữ field theo contract; JQL Phase 5 không lọc reporter
    window_days: int
    now: datetime
    max_results: int = 50
    max_pages: int = 20


@dataclass
class JiraIssueRecord:
    """Một issue đã parse từ API search (tối thiểu field cần cho báo cáo)."""

    issue_key: str
    summary: str
    due_date: str | None
    status: str
    assignee_account_id: str | None
