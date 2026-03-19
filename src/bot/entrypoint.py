"""Application entrypoint for Phase 3 Telegram state machine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from telegram.ext import Application

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.bot.handlers import register_handlers
from src.common.logging import get_logger
from src.conversation.state_machine import ConversationStateMachine, StateMachineConfig
from src.conversation.templates import load_template_bundle
from src.jira.client import JiraClient
from src.scheduler.jobs import build_scheduler
from src.storage.users_store import UsersStore


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("config/config.json must be a JSON object")
    return payload


def bootstrap_app() -> dict[str, Any]:
    logger = get_logger("bot.entrypoint")
    runtime = _load_config(Path("config/config.json"))
    template_bundle = load_template_bundle(Path("config/templates.json"))

    jira = runtime.get("jira", {})
    if not isinstance(jira, dict):
        raise ValueError("config.jira must be an object")
    http_cfg = jira.get("http", {}) if isinstance(jira.get("http"), dict) else {}

    jira_client = JiraClient(
        base_url=str(jira["base_url"]),
        email=str(jira["email"]),
        api_token=str(jira["api_token"]),
        timeout_seconds=int(http_cfg.get("timeout_seconds", 20)),
        retry_count=int(http_cfg.get("retry_count", 3)),
        retry_backoff_seconds=float(http_cfg.get("retry_backoff_seconds", 1.0)),
        attachment_max_bytes=int(jira.get("attachment_max_bytes", 10 * 1024 * 1024)),
    )

    conversation_cfg = runtime.get("conversation", {}) if isinstance(runtime.get("conversation"), dict) else {}
    telegram_cfg = runtime.get("telegram", {}) if isinstance(runtime.get("telegram"), dict) else {}
    attachments_cfg = telegram_cfg.get("attachments", {}) if isinstance(telegram_cfg.get("attachments"), dict) else {}

    state_machine = ConversationStateMachine(
        jira_client=jira_client,
        users_store=UsersStore(Path("data/users.json")),
        templates=template_bundle.bot_replies,
        intent_aliases=template_bundle.intent_aliases,
        config=StateMachineConfig(
            project_key=str(jira["project_key"]),
            issue_type_id=str(jira["issue_type_id"]),
            subtask_issue_type_id=str(jira["subtask_issue_type_id"]),
            timeout_minutes=int(conversation_cfg.get("timeout_minutes", 10)),
            attachment_max_files=int(attachments_cfg.get("max_files", 10)),
            attachment_max_total_bytes=20 * 1024 * 1024,
            attachment_max_bytes=int(jira.get("attachment_max_bytes", 10 * 1024 * 1024)),
        ),
    )

    scheduler = build_scheduler(timezone=str(jira.get("timezone", "Asia/Ho_Chi_Minh")))
    scheduler.start()
    logger.info("Scheduler started")

    token = str(telegram_cfg["bot_token"])
    application = Application.builder().token(token).build()
    register_handlers(application, state_machine)

    return {"logger": logger, "application": application, "scheduler": scheduler}


def main() -> None:
    app = bootstrap_app()
    app["logger"].info("Phase 3 state machine initialized. Start polling...")
    app["application"].run_polling()


if __name__ == "__main__":
    main()

