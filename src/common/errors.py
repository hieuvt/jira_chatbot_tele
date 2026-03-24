"""Phân loại exception dùng trong bot (Jira, validate, v.v.)."""


class BotError(Exception):
    """Lớp cơ sở cho lỗi thuộc miền nghiệp vụ bot."""


class JiraAuthError(BotError):
    """Lỗi xác thực hoặc credential Jira."""


class JiraPermissionError(BotError):
    """Lỗi quyền Jira khi kiểm tra member/admin project."""


class JiraClientError(BotError):
    """Lỗi từ JiraClient có mã `code` để map sang câu trả lời người dùng."""

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
    """Lỗi validate input từ người dùng."""
