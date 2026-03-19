"""users.json storage contract (atomic write to be implemented later)."""

from __future__ import annotations

import json
from pathlib import Path


class UsersStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def get_jira_account_id(self, telegram_account_id: str) -> str | None:
        data = self._read()
        value = data.get(telegram_account_id)
        return value if isinstance(value, str) and value.strip() else None

    def upsert_mapping(self, telegram_account_id: str, jira_account_id: str) -> bool:
        data = self._read()
        if telegram_account_id in data:
            return False
        data[telegram_account_id] = jira_account_id
        self._write(data)
        return True

    def _read(self) -> dict[str, str]:
        if not self.file_path.exists():
            return {}
        with self.file_path.open("r", encoding="utf-8") as file:
            content = json.load(file)
        if not isinstance(content, dict):
            return {}
        return {str(k): str(v) for k, v in content.items()}

    def _write(self, payload: dict[str, str]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

