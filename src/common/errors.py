"""Custom error taxonomy for bot flows."""


class BotError(Exception):
    """Base exception for bot domain."""


class JiraAuthError(BotError):
    """Jira authentication or credential issue."""


class JiraPermissionError(BotError):
    """Jira permission issue for member/admin checks."""


class ValidationError(BotError):
    """User input validation issue."""

