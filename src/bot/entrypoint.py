"""Application entrypoint for Telegram bot skeleton (Phase 1)."""

from pathlib import Path
from typing import Any

from src.common.logging import get_logger
from src.conversation.templates import load_templates
from src.scheduler.jobs import build_scheduler


def bootstrap_app() -> dict[str, Any]:
    """Boot app dependencies without business logic."""
    logger = get_logger("bot.entrypoint")
    templates_path = Path("config/templates.json")
    templates = load_templates(templates_path)

    scheduler = build_scheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.start()
    logger.info("Scheduler started with timezone Asia/Ho_Chi_Minh")

    return {"logger": logger, "templates": templates, "scheduler": scheduler}


def main() -> None:
    """Start skeleton runtime.

    NOTE: In Phase 1 this does not run a real Telegram polling loop yet.
    """
    app = bootstrap_app()
    app["logger"].info("Phase 1 skeleton initialized (polling mode planned)")


if __name__ == "__main__":
    main()

