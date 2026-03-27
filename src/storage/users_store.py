"""Lưu trữ `users.json`: mapping Telegram @username ↔ Jira; ghi atomic + file lock (Windows msvcrt / Unix fcntl)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from src.common.logging import get_logger

logger = get_logger("storage.users_store")


def _normalize_username_key(raw: str | None) -> str:
    """Chuẩn hoá username làm khóa: strip, bỏ @, lowercase."""
    if raw is None:
        return ""
    s = str(raw).strip().lstrip("@").strip()
    return s.lower()


class UsersStore:
    # Khóa 1 byte trên file `.lock` cạnh users.json (Windows: msvcrt)
    _LOCK_BYTE_LEN = 1
    _LOCK_TIMEOUT_SECONDS = 8.0  # Timeout chờ lock theo spec Phase 4
    _LOCK_RETRY_INTERVAL_SECONDS = 0.15

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        # Cùng thư mục: users.json.lock
        self.lock_path = file_path.with_name(f"{file_path.name}.lock")

    def get_jira_account_id_by_username(self, telegram_username: str) -> str | None:
        """Tra `jira_id` theo Telegram @username (đã chuẩn hoá lowercase); None nếu không có hoặc rỗng."""
        key = _normalize_username_key(telegram_username)
        if not key:
            return None
        records = self._read_file(create_if_missing=True)
        for rec in records:
            if _record_username_key(rec) != key:
                continue
            jira_raw = rec.get("jira_id")
            if isinstance(jira_raw, str) and jira_raw.strip():
                return jira_raw.strip()
        return None

    def get_jira_account_id_by_userid(self, telegram_user_id: int | str) -> str | None:
        """Tra `jira_id` theo Telegram `telegram_id`; None nếu không có hoặc rỗng."""
        key = str(telegram_user_id).strip()
        if not key:
            return None
        records = self._read_file(create_if_missing=True)
        for rec in records:
            tid_raw = rec.get("telegram_id")
            tid = str(tid_raw).strip() if tid_raw is not None else ""
            if tid != key:
                continue
            jira_raw = rec.get("jira_id")
            if isinstance(jira_raw, str) and jira_raw.strip():
                return jira_raw.strip()
        return None

    def get_reverse_mapping(self) -> dict[str, str]:
        """
        Map ngược cho reporter: key = jira_account_id, value = user_name (@username, lowercase).
        Trùng jira: giữ user_name nhỏ hơn theo so sánh chuỗi.
        """
        records = self._read_file(create_if_missing=True)
        reverse: dict[str, str] = {}
        for rec in records:
            uname = _record_username_key(rec)
            jira_raw = rec.get("jira_id")
            if not isinstance(jira_raw, str):
                continue
            jira_id = jira_raw.strip()
            if not jira_id or not uname:
                continue

            existing = reverse.get(jira_id)
            if existing is None:
                reverse[jira_id] = uname
                continue
            if uname < existing:
                reverse[jira_id] = uname
        return reverse

    def get_user_record_by_user_name(self, telegram_username: str) -> dict[str, str] | None:
        """Một bản ghi chuẩn hoá cho reporter; None nếu không có dòng."""
        key = _normalize_username_key(telegram_username)
        if not key:
            return None
        records = self._read_file(create_if_missing=True)
        for rec in records:
            if _record_username_key(rec) != key:
                continue
            un_raw = rec.get("user_name")
            dn_raw = rec.get("telegram_display_name")
            jira_raw = rec.get("jira_id")
            return {
                "user_name": str(un_raw).strip() if isinstance(un_raw, str) else "",
                "telegram_display_name": str(dn_raw).strip() if isinstance(dn_raw, str) else "",
                "jira_id": jira_raw.strip() if isinstance(jira_raw, str) else "",
            }
        return None

    def upsert_mapping(
        self,
        telegram_username: str,
        jira_account_id: str,
        *,
        telegram_display_name: str = "",
        telegram_id: str = "",
    ) -> bool:
        """
        Thêm hoặc (khi jira_id cũ invalid) ghi đè mapping. Trả True nếu đã ghi mới/đổi.
        Không ghi đè jira_id hợp lệ đã có cho cùng @username.
        telegram_username rỗng sau chuẩn hoá => no-op (user không có @username).
        `telegram_id` chỉ lưu trên đĩa (users.json), không dùng cho tra cứu trong store.
        """
        username_key = _normalize_username_key(telegram_username)
        if not username_key:
            return False

        jira_value = str(jira_account_id).strip() if jira_account_id is not None else ""
        if not jira_value:
            return False

        display_stored = str(telegram_display_name).strip() if telegram_display_name is not None else ""
        tid_stored = str(telegram_id).strip() if telegram_id is not None else ""

        try:
            with self._acquire_lock():
                records = self._read_file(create_if_missing=True)
                idx = _index_by_username_key(records, username_key)
                if idx is not None:
                    existing_jira = records[idx].get("jira_id")
                    if isinstance(existing_jira, str) and existing_jira.strip():
                        return False

                new_rec = {
                    "user_name": username_key,
                    "telegram_id": tid_stored,
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
            return _dedupe_by_username_key(_legacy_dict_to_records(content))

        if isinstance(content, list):
            return _dedupe_by_username_key(_normalize_record_list(content))

        return []

    def _write_atomic(self, records: list[dict[str, str]]) -> bool:
        """Ghi `.tmp` rồi `os.replace` sang users.json; chỉ giữ bản ghi có user_name + jira_id hợp lệ."""
        normalized: list[dict[str, str]] = []
        for rec in records:
            uname = _record_username_key(rec)
            jira_raw = rec.get("jira_id")
            if not uname:
                continue
            if not isinstance(jira_raw, str) or not jira_raw.strip():
                continue
            tid_raw = rec.get("telegram_id")
            tid_s = str(tid_raw).strip() if tid_raw is not None else ""
            normalized.append(
                {
                    "user_name": uname,
                    "telegram_id": tid_s,
                    "telegram_display_name": str(rec.get("telegram_display_name", "")).strip(),
                    "jira_id": jira_raw.strip(),
                }
            )

        normalized.sort(key=lambda r: r["user_name"])

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


def _record_username_key(rec: dict[str, str]) -> str:
    return _normalize_username_key(rec.get("user_name"))


def _dedupe_by_username_key(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Gộp trùng user_name (chuẩn hoá): bản ghi sau thắng."""
    by_key: dict[str, dict[str, str]] = {}
    for rec in records:
        key = _record_username_key(rec)
        if not key:
            continue
        by_key[key] = rec
    return list(by_key.values())


def _index_by_username_key(records: list[dict[str, str]], username_key: str) -> int | None:
    """Chỉ số dòng trong list khớp user_name (đã chuẩn hoá), hoặc None."""
    for i, rec in enumerate(records):
        if _record_username_key(rec) == username_key:
            return i
    return None


def _legacy_dict_to_records(content: dict[Any, Any]) -> list[dict[str, str]]:
    """Migrate schema cũ {telegram_id: jira_id} sang bản ghi (user_name = key chuẩn hoá)."""
    out: list[dict[str, str]] = []
    for k, v in content.items():
        tid = str(k).strip()
        if not tid:
            continue
        jira_s = v.strip() if isinstance(v, str) else ""
        out.append(
            {
                "user_name": _normalize_username_key(tid),
                "telegram_id": "",
                "telegram_display_name": "",
                "jira_id": jira_s,
            }
        )
    return out


def _normalize_record_list(content: list[Any]) -> list[dict[str, str]]:
    """Chuẩn hoá phần tử list object từ JSON thành dict đồng nhất (giữ `telegram_id` nếu có)."""
    out: list[dict[str, str]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        un_raw = item.get("user_name")
        user_part = str(un_raw).strip() if isinstance(un_raw, str) else ""
        tid_raw = item.get("telegram_id")
        tid_for_key = str(tid_raw).strip() if tid_raw is not None and str(tid_raw).strip() else ""
        tid_stored = str(tid_raw).strip() if tid_raw is not None else ""

        key = _normalize_username_key(user_part) if user_part else _normalize_username_key(tid_for_key)
        if not key:
            continue

        jira_raw = item.get("jira_id")
        jira_s = jira_raw.strip() if isinstance(jira_raw, str) else ""

        dn = item.get("telegram_display_name")
        display_name = str(dn).strip() if isinstance(dn, str) else ""

        out.append(
            {
                "user_name": key,
                "telegram_id": tid_stored,
                "telegram_display_name": display_name,
                "jira_id": jira_s,
            }
        )
    return out
