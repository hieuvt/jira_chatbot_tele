"""Jira permission check contracts (skeleton)."""


class PermissionClientProtocol:
    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        raise NotImplementedError

