"""Giao thức (protocol) kiểm tra quyền / query Jira — khung tham chiếu, triển khai thực tế ở `JiraClient`."""

from src.jira.models import QueryIssuesRequest


class PermissionClientProtocol:
    """Interface: membership, admin project, và query due issues."""

    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

    def query_issues_by_due_date_for_reporter(self, query: QueryIssuesRequest) -> object:
        raise NotImplementedError
