"""Lưu trữ `users.json`: mapping Telegram ↔ Jira; ghi atomic + file lock (Windows msvcrt / Unix fcntl)."""

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
    # Khóa 1 byte trên file `.lock` cạnh users.json (Windows: msvcrt)
    _LOCK_BYTE_LEN = 1
    _LOCK_TIMEOUT_SECONDS = 8.0  # Timeout chờ lock theo spec Phase 4
    _LOCK_RETRY_INTERVAL_SECONDS = 0.15

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        # Cùng thư mục: users.json.lock
        self.lock_path = file_path.with_name(f"{file_path.name}.lock")

    def get_jira_account_id(self, telegram_account_id: str) -> str | None:
        """Tra `jira_id` theo `telegram_id`; None nếu không có hoặc giá trị rỗng."""
        if telegram_account_id is None or not str(telegram_account_id).strip():
            return None
        records = self._read_file(create_if_missing=True)
        key = str(telegram_account_id).strip()
        for rec in records:
            if rec.get("telegram_id") != key:
                continue
            jira_raw = rec.get("jira_id")
            if isinstance(jira_raw, str) and jira_raw.strip():
                return jira_raw.strip()
        return None

    def get_reverse_mapping(self) -> dict[str, str]:
        """
        Map ngược cho reporter: key = jira_account_id, value = telegram_account_id.
        Trùng jira: giữ telegram_id nhỏ hơn (so sánh int nếu được).
        """
        records = self._read_file(create_if_missing=True)
        reverse: dict[str, str] = {}
        for rec in records:
            telegram_id = str(rec.get("telegram_id", "")).strip()
            jira_raw = rec.get("jira_id")
            if not isinstance(jira_raw, str):
                continue
            jira_id = jira_raw.strip()
            if not jira_id or not telegram_id:
                continue

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

    def get_user_record_by_telegram_id(self, telegram_account_id: str) -> dict[str, str] | None:
        """
        Một bản ghi đầy đủ (chuẩn hoá key string) cho reporter; None nếu không có dòng.
        """
        if telegram_account_id is None or not str(telegram_account_id).strip():
            return None
        key = str(telegram_account_id).strip()
        records = self._read_file(create_if_missing=True)
        for rec in records:
            if str(rec.get("telegram_id", "")).strip() != key:
                continue
            un_raw = rec.get("user_name")
            dn_raw = rec.get("telegram_display_name")
            jira_raw = rec.get("jira_id")
            return {
                "user_name": str(un_raw).strip() if isinstance(un_raw, str) else "",
                "telegram_id": key,
                "telegram_display_name": str(dn_raw).strip() if isinstance(dn_raw, str) else "",
                "jira_id": jira_raw.strip() if isinstance(jira_raw, str) else "",
            }
        return None

    def upsert_mapping(
        self,
        telegram_account_id: str,
        jira_account_id: str,
        *,
        user_name: str = "",
        telegram_display_name: str = "",
    ) -> bool:
        """
        Thêm hoặc (khi jira_id cũ invalid) ghi đè mapping. Trả True nếu đã ghi mới/đổi.
        Không ghi đè jira_id hợp lệ đã có cho cùng telegram_id.
        """
        telegram_key = str(telegram_account_id).strip() if telegram_account_id is not None else ""
        if not telegram_key:
            return False

        jira_value = str(jira_account_id).strip() if jira_account_id is not None else ""
        if not jira_value:
            return False

        name_stored = str(user_name).strip() if user_name is not None else ""
        if not name_stored:
            name_stored = telegram_key

        display_stored = str(telegram_display_name).strip() if telegram_display_name is not None else ""

        try:
            with self._acquire_lock():
                records = self._read_file(create_if_missing=True)
                idx = _index_by_telegram_id(records, telegram_key)
                if idx is not None:
                    existing_jira = records[idx].get("jira_id")
                    if isinstance(existing_jira, str) and existing_jira.strip():
                        return False

                new_rec = {
                    "user_name": name_stored,
                    "telegram_id": telegram_key,
                    "telegram_display_name": display_stored,
                    "jira_id": jira_value,
                }
                if idx is not None:
                    records[idx] = new_rec
                else:
                    records.append(new_rec)
                return self._write_atomic(records)
        except TimeoutError:
            return False
        except OSError:
            return False

    def _read_file(self, *, create_if_missing: bool) -> list[dict[str, str]]:
        # Hàm không giữ lock — caller cần atomic thì bọc `_acquire_lock()`
        if create_if_missing and not self.file_path.exists():
            try:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                self.file_path.write_text("[]", encoding="utf-8")
            except OSError:
                logger.exception("Failed creating users.json for %s", self.file_path)
                return []

        if not self.file_path.exists():
            return []

        try:
            raw = self.file_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed reading users.json for %s", self.file_path)
            return []
        if not raw.strip():
            return []

        try:
            content = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Invalid JSON in users.json at %s (treating as empty; recover on upsert): %s",
                self.file_path,
                exc.msg,
            )
            return []

        if isinstance(content, dict):
            return _dedupe_by_telegram_id(_legacy_dict_to_records(content))

        if isinstance(content, list):
            return _dedupe_by_telegram_id(_normalize_record_list(content))

        return []

    def _write_atomic(self, records: list[dict[str, str]]) -> bool:
        """Ghi `.tmp` rồi `os.replace` sang users.json; chỉ giữ bản ghi có jira_id hợp lệ."""
        normalized: list[dict[str, str]] = []
        for rec in records:
            tid = str(rec.get("telegram_id", "")).strip()
            jira_raw = rec.get("jira_id")
            if not tid:
                continue
            if not isinstance(jira_raw, str) or not jira_raw.strip():
                continue
            normalized.append(
                {
                    "user_name": str(rec.get("user_name", "")).strip() or tid,
                    "telegram_id": tid,
                    "telegram_display_name": str(rec.get("telegram_display_name", "")).strip(),
                    "jira_id": jira_raw.strip(),
                }
            )

        normalized.sort(key=lambda r: r["telegram_id"])

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
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    @contextmanager
    def _acquire_lock(self):
        """Context manager: acquire lock file không blocking với retry; TimeoutError nếu quá hạn."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.lock_path.open("a+b")
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()

            start = time.monotonic()
            try:
                import msvcrt  # type: ignore

                use_msvcrt = True
            except ImportError:  # pragma: no cover
                use_msvcrt = False

            while True:
                try:
                    lock_file.seek(0)
                    if use_msvcrt:
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


def _dedupe_by_telegram_id(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Gộp trùng telegram_id: bản ghi sau thắng."""
    by_id: dict[str, dict[str, str]] = {}
    for rec in records:
        tid = str(rec.get("telegram_id", "")).strip()
        if not tid:
            continue
        by_id[tid] = rec
    return list(by_id.values())


def _index_by_telegram_id(records: list[dict[str, str]], telegram_key: str) -> int | None:
    """Chỉ số dòng trong list khớp telegram_id, hoặc None."""
    for i, rec in enumerate(records):
        if str(rec.get("telegram_id", "")).strip() == telegram_key:
            return i
    return None


def _legacy_dict_to_records(content: dict[Any, Any]) -> list[dict[str, str]]:
    """Migrate schema cũ {telegram_id: jira_id} sang list bản ghi chuẩn."""
    out: list[dict[str, str]] = []
    for k, v in content.items():
        tid = str(k).strip()
        if not tid:
            continue
        jira_s = v.strip() if isinstance(v, str) else ""
        out.append(
            {
                "user_name": "",
                "telegram_id": tid,
                "telegram_display_name": "",
                "jira_id": jira_s,
            }
        )
    return out


def _normalize_record_list(content: list[Any]) -> list[dict[str, str]]:
    """Chuẩn hoá phần tử list object từ JSON thành dict đồng nhất."""
    out: list[dict[str, str]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        tid_raw = item.get("telegram_id")
        if tid_raw is None:
            continue
        tid = str(tid_raw).strip()
        if not tid:
            continue
        jira_raw = item.get("jira_id")
        jira_s = jira_raw.strip() if isinstance(jira_raw, str) else ""

        un = item.get("user_name")
        user_name = str(un).strip() if isinstance(un, str) else ""

        dn = item.get("telegram_display_name")
        display_name = str(dn).strip() if isinstance(dn, str) else ""

        out.append(
            {
                "user_name": user_name,
                "telegram_id": tid,
                "telegram_display_name": display_name,
                "jira_id": jira_s,
            }
        )
    return out
