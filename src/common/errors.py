"""Custom error taxonomy for bot flows."""


class BotError(Exception):
    """Base exception for bot domain."""


class JiraAuthError(BotError):
    """Jira authentication or credential issue."""


class JiraPermissionError(BotError):
    """Jira permission issue for member/admin checks."""


class JiraClientError(BotError):
    """Typed Jira client error for template mapping."""

    def __init__(
        self,
        code: str,
        message: str,
        context: dict[str, object] | None = None,
        retriable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}
        self.retriable = retriable


class ValidationError(BotError):
    """User input validation issue."""

