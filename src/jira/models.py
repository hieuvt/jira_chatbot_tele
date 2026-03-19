"""Jira DTO models for skeleton contracts."""

from dataclasses import dataclass, field


@dataclass
class IssueCreateRequest:
    project_key: str
    summary: str
    description: str
    assignee_account_id: str
    due_date: str
    issue_type: str = "TASK"


@dataclass
class AttachmentMeta:
    filename: str
    size_bytes: int
    telegram_file_id: str


@dataclass
class SubtaskCreateRequest:
    parent_issue_key: str
    issue_type: str
    checklist_items: list[str] = field(default_factory=list)

