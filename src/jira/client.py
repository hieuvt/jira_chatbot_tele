"""Jira REST client abstraction (skeleton)."""

from src.jira.models import AttachmentMeta, IssueCreateRequest, SubtaskCreateRequest


class JiraClient:
    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        _ = (jira_account_id, project_key)
        return False

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        _ = (jira_account_id, project_key)
        return False

    def create_issue(self, request: IssueCreateRequest) -> str:
        _ = request
        return "SKELETON-1"

    def create_subtasks(self, request: SubtaskCreateRequest) -> list[str]:
        _ = request
        return []

    def upload_attachments(self, issue_key: str, files: list[AttachmentMeta]) -> list[str]:
        _ = (issue_key, files)
        return []

