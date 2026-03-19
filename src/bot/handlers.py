"""Telegram handlers registry (skeleton only)."""

from collections.abc import Callable


def register_handlers(application: object, on_message: Callable[..., object]) -> None:
    """Register handlers into Telegram application.

    Placeholder for Phase 3 integration with python-telegram-bot.
    """
    _ = (application, on_message)

