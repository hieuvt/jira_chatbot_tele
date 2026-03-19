"""Jira permission check contracts (skeleton)."""

from src.jira.models import QueryIssuesRequest


class PermissionClientProtocol:
    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

    def query_issues_by_due_date_for_reporter(self, query: QueryIssuesRequest) -> object:
        raise NotImplementedError

