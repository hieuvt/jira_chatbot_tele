"""Shared helpers for Phase 2 Jira client smoke tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.jira.client import JiraClient


def load_runtime_config(config_path: str = "config/config.json") -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    if not isinstance(config, dict):
        raise ValueError("config file must be a JSON object")
    return config


def build_jira_client(config: dict[str, Any]) -> JiraClient:
    jira = config.get("jira", {})
    if not isinstance(jira, dict):
        raise ValueError("config.jira must be an object")
    http_cfg = jira.get("http", {}) if isinstance(jira.get("http"), dict) else {}
    return JiraClient(
        base_url=str(jira["base_url"]),
        email=str(jira["email"]),
        api_token=str(jira["api_token"]),
        timeout_seconds=int(http_cfg.get("timeout_seconds", 20)),
        retry_count=int(http_cfg.get("retry_count", 3)),
        retry_backoff_seconds=float(http_cfg.get("retry_backoff_seconds", 1.0)),
        attachment_max_bytes=int(jira.get("attachment_max_bytes", 10 * 1024 * 1024)),
    )


def get_jira_settings(config: dict[str, Any]) -> dict[str, Any]:
    jira = config.get("jira", {})
    if not isinstance(jira, dict):
        raise ValueError("config.jira must be an object")
    return jira
