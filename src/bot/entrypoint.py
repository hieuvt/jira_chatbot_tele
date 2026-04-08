"""Điểm vào ứng dụng: nạp config, Jira, state machine, reporter, scheduler, chạy long polling Telegram."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram.ext import Application

# Đảm bảo import `src.*` khi chạy file này trực tiếp
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.bot.handlers import conversation_reminder_post_init, register_handlers
from src.common.logging import get_logger
from src.common.errors import JiraClientError
from src.conversation.state_machine import ConversationStateMachine, StateMachineConfig
from src.conversation.templates import load_template_bundle
from src.jira.client import JiraClient
from src.llm.gemini_client import GeminiClient, GeminiConfig
from src.llm.poem_service import PoemService, PoemServiceConfig
from src.jira.models import IssueCreateRequest
from src.reports.reporter import Reporter
from src.scheduler.jobs import (
    build_scheduler,
    configure_monthly_task_jobs,
    configure_phase5_report_jobs,
    should_run_monthly_today,
)
from src.storage.users_store import UsersStore


def _load_config(config_path: Path) -> dict[str, Any]:
    """Đọc JSON runtime config; bắt buộc là object ở root."""
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("config/config.json must be a JSON object")
    return payload


def bootstrap_app() -> dict[str, Any]:
    """Dựng toàn bộ dependency và trả về logger, Application Telegram, scheduler."""
    logger = get_logger("bot.entrypoint")
    # Luôn resolve từ root repo để config/users.json không phụ thuộc CWD khi chạy
    config_path = project_root / "config" / "config.json"
    templates_path = project_root / "config" / "templates.json"
    users_path = project_root / "data" / "users.json"
    logger.info("Users store file: %s", users_path)

    runtime = _load_config(config_path)
    template_bundle = load_template_bundle(templates_path)

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
    timeout_minutes = int(conversation_cfg.get("timeout_minutes", 10))
    reminder_after_minutes = int(conversation_cfg.get("reminder_after_minutes", 5))
    require_proof_photo_on_mark_done = bool(conversation_cfg.get("require_proof_photo_on_mark_done", False))
    if not (0 < reminder_after_minutes < timeout_minutes):
        raise ValueError(
            "conversation.reminder_after_minutes must satisfy 0 < reminder_after_minutes < timeout_minutes; "
            f"got reminder_after_minutes={reminder_after_minutes}, timeout_minutes={timeout_minutes}"
        )
    telegram_cfg = runtime.get("telegram", {}) if isinstance(runtime.get("telegram"), dict) else {}
    attachments_cfg = telegram_cfg.get("attachments", {}) if isinstance(telegram_cfg.get("attachments"), dict) else {}

    due_cfg = runtime.get("due", {}) if isinstance(runtime.get("due"), dict) else {}
    notification_cfg = due_cfg.get("notification", {}) if isinstance(due_cfg.get("notification"), dict) else {}
    report_timezone = str(notification_cfg.get("report_timezone", "Asia/Ho_Chi_Minh"))
    window_days = int(notification_cfg.get("window_days", 3))
    report_times = notification_cfg.get("report_times", ["08:00", "17:00"])
    if not isinstance(report_times, list):
        report_times = ["08:00", "17:00"]
    completed_status_names = notification_cfg.get("completed_status_names", ["Done"])
    if not isinstance(completed_status_names, list) or not completed_status_names:
        completed_status_names = ["Done"]
    completed_lookback_hours = int(notification_cfg.get("completed_lookback_hours", 24))
    monthly_tasks_raw = notification_cfg.get("monthly_tasks", [])
    monthly_tasks = monthly_tasks_raw if isinstance(monthly_tasks_raw, list) else []

    users_store = UsersStore(users_path)

    token = str(telegram_cfg["bot_token"])
    reporter = Reporter(
        jira_client=jira_client,
        users_store=users_store,
        project_key=str(jira["project_key"]),
        bot_token=token,
        logger=logger,
        lookback_hours=completed_lookback_hours,
        completed_status_names=[str(x).strip() for x in completed_status_names if str(x).strip()],
        require_proof_photo_on_mark_done=require_proof_photo_on_mark_done,
    )

    poem_service = _build_poem_service(runtime=runtime)

    state_machine = ConversationStateMachine(
        jira_client=jira_client,
        users_store=users_store,
        templates=template_bundle.bot_replies,
        intent_aliases=template_bundle.intent_aliases,
        reporter=reporter,
        poem_service=poem_service,
        config=StateMachineConfig(
            project_key=str(jira["project_key"]),
            issue_type_id=str(jira["issue_type_id"]),
            subtask_issue_type_id=str(jira["subtask_issue_type_id"]),
            timeout_minutes=timeout_minutes,
            reminder_after_minutes=reminder_after_minutes,
            attachment_max_files=int(attachments_cfg.get("max_files", 10)),
            attachment_max_total_bytes=20 * 1024 * 1024,
            attachment_max_bytes=int(jira.get("attachment_max_bytes", 10 * 1024 * 1024)),
            my_task_window_days=window_days,
            my_task_completed_lookback_hours=completed_lookback_hours,
            my_task_completed_status_names=[str(x).strip() for x in completed_status_names if str(x).strip()],
            report_window_days=window_days,
            report_timezone=report_timezone,
            require_proof_photo_on_mark_done=require_proof_photo_on_mark_done,
        ),
    )

    application = Application.builder().token(token).post_init(conversation_reminder_post_init).build()
    tpl_cancelled = str(template_bundle.bot_replies.get("TPL_CANCELLED", ""))
    register_handlers(application, state_machine, tpl_cancelled=tpl_cancelled)

    scheduler = build_scheduler(timezone=report_timezone)

    allowed_chat_ids = telegram_cfg.get("allowed_chat_ids", [])
    telegram_chat_id_first: int | None = None
    if isinstance(allowed_chat_ids, list) and allowed_chat_ids:
        try:
            telegram_chat_id_first = int(str(allowed_chat_ids[0]).strip())
        except Exception:
            telegram_chat_id_first = None

    def _phase5_job_callback() -> None:
        """Job định kỳ: build báo cáo due date và gửi chat đầu tiên trong allowed_chat_ids."""
        trace_id = uuid.uuid4().hex[:12]
        if telegram_chat_id_first is None:
            logger.error("Phase5: allowed_chat_ids missing/invalid. trace_id=%s", trace_id)
            return

        try:
            tz = ZoneInfo(report_timezone)
        except Exception:
            # Môi trường thiếu tzdata (Windows): fallback offset cho HCM hoặc UTC
            if str(report_timezone).lower() == "asia/ho_chi_minh":
                tz = timezone(timedelta(hours=7))
            else:
                tz = timezone.utc
        now = datetime.now(tz=tz)
        logger.info("Phase5 report start trace_id=%s now=%s", trace_id, now.isoformat())
        try:
            message_texts = reporter.build_report_messages(window_days=window_days, now=now)
            reporter.send_report(telegram_chat_id=telegram_chat_id_first, message_texts=message_texts)
            logger.info("Phase5 report sent trace_id=%s messages=%d", trace_id, len(message_texts))
            if poem_service is not None:
                poem = poem_service.make_encouragement_poem(
                    context="Hoàn tất gửi báo cáo định kỳ theo lịch tự động."
                )
                if poem:
                    import html as _html

                    reporter.send_report(
                        telegram_chat_id=telegram_chat_id_first,
                        message_texts=[_html.escape(poem)],
                    )
        except JiraClientError:
            logger.exception("Phase5: Jira error trace_id=%s", trace_id)
            try:
                reporter.send_report(
                    telegram_chat_id=telegram_chat_id_first, message_texts=["hệ thống đang lỗi"]
                )
            except Exception:
                logger.exception("Phase5: failed to send error message trace_id=%s", trace_id)
        except Exception:
            logger.exception("Phase5: unexpected error trace_id=%s", trace_id)
            try:
                reporter.send_report(
                    telegram_chat_id=telegram_chat_id_first, message_texts=["hệ thống đang lỗi"]
                )
            except Exception:
                logger.exception("Phase5: failed to send error message trace_id=%s", trace_id)

    def _monthly_task_callback(*, task_index: int, day_of_month: int) -> None:
        trace_id = uuid.uuid4().hex[:12]
        if telegram_chat_id_first is None:
            logger.error("MonthlyTask: allowed_chat_ids missing/invalid. trace_id=%s", trace_id)
            return
        if task_index < 0 or task_index >= len(monthly_tasks):
            logger.error("MonthlyTask: invalid task index=%s trace_id=%s", task_index, trace_id)
            return

        task_cfg = monthly_tasks[task_index]
        if not isinstance(task_cfg, dict):
            logger.error("MonthlyTask: task config is not object index=%s trace_id=%s", task_index, trace_id)
            return

        try:
            tz = ZoneInfo(report_timezone)
        except Exception:
            if str(report_timezone).lower() == "asia/ho_chi_minh":
                tz = timezone(timedelta(hours=7))
            else:
                tz = timezone.utc
        now = datetime.now(tz=tz)
        if not should_run_monthly_today(day_of_month=day_of_month, now=now):
            logger.info(
                "MonthlyTask skip (not target day) idx=%s day=%s now=%s trace_id=%s",
                task_index,
                day_of_month,
                now.isoformat(),
                trace_id,
            )
            return

        assignee_jira_id = str(task_cfg.get("assignee_jira_id", "")).strip()
        task_name = str(task_cfg.get("task_name", "")).strip()
        task_description = str(task_cfg.get("task_description", "")).strip()
        try:
            due_days = int(task_cfg.get("due_days", 0))
        except Exception:
            due_days = 0
        if not assignee_jira_id or not task_name or not task_description or due_days <= 0:
            logger.error(
                "MonthlyTask invalid config idx=%s assignee=%s due_days=%s trace_id=%s",
                task_index,
                bool(assignee_jira_id),
                due_days,
                trace_id,
            )
            return

        due_date = (now.date() + timedelta(days=due_days)).isoformat()
        reverse = users_store.get_reverse_mapping()
        assignee_username = reverse.get(assignee_jira_id)
        assignee_display = f"@{assignee_username}" if assignee_username else assignee_jira_id

        try:
            issue_key = jira_client.create_issue(
                IssueCreateRequest(
                    project_key=str(jira["project_key"]),
                    summary=task_name,
                    description=task_description,
                    assignee_account_id=assignee_jira_id,
                    due_date=due_date,
                    issue_type_id=str(jira["issue_type_id"]),
                )
            )
            issue_url = f"{jira_client.base_url}/browse/{issue_key}" if getattr(jira_client, "base_url", None) else ""
            msg = (
                f"Tạo công việc định kỳ hàng tháng thành công: {issue_key}\n"
                f"Assignee: {assignee_display}\n"
                f"Summary: {task_name}\n"
                f"Description: {task_description}\n"
                f"Link Jira: {issue_url}\n"
                f"Số checklist items: 0\n"
                f"Số file upload: 0"
            )
            reporter.send_report(telegram_chat_id=telegram_chat_id_first, message_texts=[msg])
            logger.info("MonthlyTask created idx=%s issue=%s trace_id=%s", task_index, issue_key, trace_id)
        except JiraClientError:
            logger.exception("MonthlyTask Jira error idx=%s trace_id=%s", task_index, trace_id)
            try:
                reporter.send_report(telegram_chat_id=telegram_chat_id_first, message_texts=["hệ thống đang lỗi"])
            except Exception:
                logger.exception("MonthlyTask failed to send error message trace_id=%s", trace_id)
        except Exception:
            logger.exception("MonthlyTask unexpected error idx=%s trace_id=%s", task_index, trace_id)
            try:
                reporter.send_report(telegram_chat_id=telegram_chat_id_first, message_texts=["hệ thống đang lỗi"])
            except Exception:
                logger.exception("MonthlyTask failed to send error message trace_id=%s", trace_id)

    configure_phase5_report_jobs(
        scheduler=scheduler,
        timezone=report_timezone,
        report_times=report_times,
        job_callback=_phase5_job_callback,
    )
    configure_monthly_task_jobs(
        scheduler=scheduler,
        timezone=report_timezone,
        monthly_tasks=monthly_tasks,
        job_callback=_monthly_task_callback,
    )

    scheduler.start()
    logger.info("Scheduler started (Phase5 + MonthlyTasks)")

    return {"logger": logger, "application": application, "scheduler": scheduler}


def _build_poem_service(*, runtime: dict[str, Any]) -> PoemService | None:
    llm = runtime.get("llm", {}) if isinstance(runtime.get("llm"), dict) else {}
    enabled = bool(llm.get("enabled", True))
    if not enabled:
        return None
    prompts = llm.get("prompts", {}) if isinstance(llm.get("prompts"), dict) else {}
    prompt_path_raw = str(prompts.get("encourage_poem_path", "")).strip()
    if not prompt_path_raw:
        return None
    prompt_path = str((project_root / prompt_path_raw).resolve())

    gem = llm.get("gemini", {}) if isinstance(llm.get("gemini"), dict) else {}
    api_key = str(gem.get("api_key", "")).strip()
    base_url = str(gem.get("base_url", "https://generativelanguage.googleapis.com")).strip()
    api_version = str(gem.get("api_version", "v1beta")).strip()
    model = str(gem.get("model", "gemini-2.0-flash")).strip()
    timeout_seconds = int(llm.get("timeout_seconds", 20))

    gemini = GeminiClient(
        GeminiConfig(
            base_url=base_url,
            api_version=api_version,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    )
    return PoemService(cfg=PoemServiceConfig(enabled=True, prompt_path=prompt_path), gemini=gemini)


def main() -> None:
    """Chạy bot: bootstrap + run_polling."""
    app = bootstrap_app()
    app["logger"].info("Phase 3 state machine initialized. Start polling...")
    app["application"].run_polling()


if __name__ == "__main__":
    main()

