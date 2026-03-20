"""users.json storage contract (atomic write + concurrency safety)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from src.common.logging import get_logger

logger = get_logger("storage.users_store")


class UsersStore:
    # Windows file locking via msvcrt.
    # We lock a single byte in a dedicated lock file.
    _LOCK_BYTE_LEN = 1
    _LOCK_TIMEOUT_SECONDS = 8.0  # ~5-10 seconds as Phase 4 spec
    _LOCK_RETRY_INTERVAL_SECONDS = 0.15

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        # users.json -> users.json.lock
        self.lock_path = file_path.with_name(f"{file_path.name}.lock")

    def get_jira_account_id(self, telegram_account_id: str) -> str | None:
        if telegram_account_id is None or not str(telegram_account_id).strip():
            return None
        data = self._read_file(create_if_missing=True)
        value = data.get(str(telegram_account_id).strip())
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def get_reverse_mapping(self) -> dict[str, str]:
        """
        Reverse mapping used by Phase 5 reporter:
        - key: jira_account_id
        - value: telegram_account_id
        """
        data = self._read_file(create_if_missing=True)
        reverse: dict[str, str] = {}
        for telegram_id_raw, jira_value_raw in data.items():
            if not isinstance(jira_value_raw, str):
                continue
            jira_id = jira_value_raw.strip()
            telegram_id = str(telegram_id_raw).strip()
            if not jira_id or not telegram_id:
                continue

            # If multiple telegram users map to the same Jira account,
            # keep the smallest numeric telegram id (best-effort deterministic).
            existing = reverse.get(jira_id)
            if existing is None:
                reverse[jira_id] = telegram_id
                continue

            try:
                if int(telegram_id) < int(existing):
                    reverse[jira_id] = telegram_id
            except ValueError:
                if telegram_id < existing:
                    reverse[jira_id] = telegram_id
        return reverse

    def upsert_mapping(self, telegram_account_id: str, jira_account_id: str) -> bool:
        telegram_key = str(telegram_account_id).strip() if telegram_account_id is not None else ""
        if not telegram_key:
            return False

        jira_value = str(jira_account_id).strip() if jira_account_id is not None else ""
        if not jira_value:
            return False

        try:
            with self._acquire_lock():
                data = self._read_file(create_if_missing=True)
                existing = data.get(telegram_key)
                existing_valid = isinstance(existing, str) and existing.strip()
                if existing_valid:
                    # Keep mapping if it already exists & is valid.
                    return False

                data[telegram_key] = jira_value
                return self._write_atomic(data)
        except TimeoutError:
            return False
        except OSError:
            # IO / permission errors or lock errors -> fail closed (no write)
            return False

    def _read_file(self, *, create_if_missing: bool) -> dict[str, Any]:
        # NOTE: this function intentionally does not hold the lock.
        # Callers that need strict atomicity (upsert) must wrap it with _acquire_lock().
        if create_if_missing and not self.file_path.exists():
            try:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                # Create empty valid JSON for resilience contract.
                self.file_path.write_text("{}", encoding="utf-8")
            except OSError:
                logger.exception("Failed creating users.json for %s", self.file_path)
                return {}

        if not self.file_path.exists():
            return {}

        try:
            raw = self.file_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed reading users.json for %s", self.file_path)
            return {}
        if not raw.strip():
            return {}

        try:
            content = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Invalid JSON => treat as empty; upsert will rewrite correct format.
            # Ops visibility without traceback: recover path is expected, not a crash.
            logger.warning(
                "Invalid JSON in users.json at %s (treating as empty; recover on upsert): %s",
                self.file_path,
                exc.msg,
            )
            return {}

        if not isinstance(content, dict):
            return {}

        # Preserve value types for validation logic.
        return {str(k): v for k, v in content.items()}

    def _write_atomic(self, payload: dict[str, Any]) -> bool:
        # Ensure JSON keys/values are valid contract types.
        # Do not "trim" existing string values here: Phase 4 says keep existing valid mappings.
        normalized: dict[str, str] = {}
        for k, v in payload.items():
            key = str(k)
            if not key:
                continue
            if not isinstance(v, str):
                continue
            if not v.strip():
                continue
            normalized[key] = v

        tmp_path = self.file_path.with_name(f"{self.file_path.name}.tmp")
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(normalized, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())

            os.replace(tmp_path, self.file_path)
            return True
        except OSError:
            # Fail closed: do not touch users.json on write/replace errors.
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    @contextmanager
    def _acquire_lock(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+b")
        try:
            # Ensure there's at least 1 byte so the lock region is valid.
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()

            start = time.monotonic()
            # Prefer Windows msvcrt; fallback to fcntl on non-Windows.
            try:
                import msvcrt  # type: ignore

                use_msvcrt = True
            except ImportError:  # pragma: no cover
                use_msvcrt = False

            while True:
                try:
                    lock_file.seek(0)
                    if use_msvcrt:
                        # Non-blocking lock; retry until timeout.
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, self._LOCK_BYTE_LEN)
                    else:  # pragma: no cover
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() - start > self._LOCK_TIMEOUT_SECONDS:
                        raise TimeoutError(f"Timeout acquiring lock for {self.lock_path}")
                    time.sleep(self._LOCK_RETRY_INTERVAL_SECONDS)

            yield
        finally:
            # Unlock + close.
            try:
                try:
                    import msvcrt  # type: ignore

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, self._LOCK_BYTE_LEN)
                except ImportError:  # pragma: no cover
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                lock_file.close()
            except OSError:
                pass

