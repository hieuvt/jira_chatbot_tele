"""Jira DTO models for Jira Cloud contracts."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IssueCreateRequest:
    project_key: str
    summary: str
    description: str
    assignee_account_id: str
    due_date: str
    issue_type_id: str


@dataclass
class AttachmentMeta:
    filename: str
    size_bytes: int
    telegram_file_id: str
    content_bytes: bytes
    content_type: str = "application/octet-stream"


@dataclass
class SubtaskCreateRequest:
    parent_issue_key: str
    issue_type_id: str
    checklist_items: list[str] = field(default_factory=list)


@dataclass
class QueryIssuesRequest:
    project_key: str
    reporter_account_id: str
    window_days: int
    now: datetime
    max_results: int = 50
    max_pages: int = 20


@dataclass
class JiraIssueRecord:
    issue_key: str
    summary: str
    due_date: str | None
    status: str
    assignee_account_id: str | None

