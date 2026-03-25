"""Test UsersStore: get/upsert, JSON lỗi, ghi atomic (không mạng).

Usage:
  python scripts/phase4_users_store_test.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT_DIR))

from src.storage.users_store import UsersStore  # noqa: E402


def _check(condition: bool, label: str) -> int:
    if condition:
        print(f"[OK] {label}")
        return 0
    print(f"[FAIL] {label}")
    return 1


def _jira_for_username(content: Any, username: str) -> str | None:
    if not isinstance(content, list):
        return None
    key = str(username).strip().lstrip("@").strip().lower()
    for rec in content:
        if not isinstance(rec, dict):
            continue
        un = str(rec.get("user_name", "")).strip().lower()
        if un == key:
            v = rec.get("jira_id")
            return v if isinstance(v, str) else None
    return None


def _record_for_username(content: Any, username: str) -> dict[str, Any] | None:
    if not isinstance(content, list):
        return None
    key = str(username).strip().lstrip("@").strip().lower()
    for rec in content:
        if not isinstance(rec, dict):
            continue
        un = str(rec.get("user_name", "")).strip().lower()
        if un == key:
            return rec
    return None


def test_get_jira_account_id_empty_and_invalid() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"
        p.write_text("{}", encoding="utf-8")
        store = UsersStore(p)

        failures += _check(store.get_jira_account_id("alice") is None, "get: missing key => None")
        failures += _check(store.get_jira_account_id("   ") is None, "get: whitespace username => None")

        p.write_text(json.dumps({"1": "   "}), encoding="utf-8")
        failures += _check(store.get_jira_account_id("1") is None, "get: legacy dict blank value => None")
        p.write_text(json.dumps({"2": 123}), encoding="utf-8")
        failures += _check(store.get_jira_account_id("2") is None, "get: legacy non-string value => None")

    return failures


def test_upsert_validation_and_no_overwrite_valid() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"
        store = UsersStore(p)

        failures += _check(not store.upsert_mapping("   ", "jira-1"), "upsert: blank username => no-op")
        failures += _check(not p.exists(), "upsert: blank username => does not create file")

        failures += _check(not store.upsert_mapping("alice", "   "), "upsert: blank jira id => no-op")
        failures += _check(not p.exists(), "upsert: blank jira id => does not create file")

        added = store.upsert_mapping(
            "alice",
            "jira-1",
            telegram_display_name="Alice A",
            telegram_id="111",
        )
        failures += _check(added, "upsert: add when key missing => added=true")
        failures += _check(p.exists(), "upsert: creates users.json when valid input")
        failures += _check(store.get_jira_account_id("alice") == "jira-1", "get after add => stored mapping")
        failures += _check(store.get_jira_account_id("Alice") == "jira-1", "get case-insensitive username")

        content_alice = json.loads(p.read_text(encoding="utf-8"))
        rec_alice = _record_for_username(content_alice, "alice")
        failures += _check(
            isinstance(rec_alice, dict) and rec_alice.get("telegram_id") == "111",
            "upsert: telegram_id persisted on disk",
        )
        rec_api = store.get_user_record_by_user_name("alice")
        failures += _check(
            rec_api is not None and "telegram_id" not in rec_api,
            "get_user_record_by_user_name: does not expose telegram_id",
        )

        added2 = store.upsert_mapping("alice", "jira-2", telegram_display_name="Alice A")
        failures += _check(not added2, "upsert: existing valid mapping => added=false")
        failures += _check(store.get_jira_account_id("alice") == "jira-1", "upsert: existing valid mapping preserved")

    return failures


def test_upsert_overwrite_invalid_value() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"
        p.write_text(json.dumps({"1": "   ", "2": "ok"}), encoding="utf-8")
        store = UsersStore(p)

        added = store.upsert_mapping("1", "jira-1-new", telegram_display_name="")
        failures += _check(added, "upsert: overwrite when existing legacy value is blank string")
        failures += _check(store.get_jira_account_id("1") == "jira-1-new", "upsert: overwritten value is retrievable")
        failures += _check(store.get_jira_account_id("2") == "ok", "upsert: keeps other valid mappings")

        p.write_text(json.dumps({"3": 123}), encoding="utf-8")
        store2 = UsersStore(p)
        added2 = store2.upsert_mapping("3", "jira-3", telegram_display_name="")
        failures += _check(added2, "upsert: overwrite when existing value is non-string")
        failures += _check(store2.get_jira_account_id("3") == "jira-3", "upsert: overwritten non-string mapping works")

    return failures


def test_upsert_resilience_invalid_json_and_atomicity() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"
        p.write_text("{not-json", encoding="utf-8")
        store = UsersStore(p)

        added = store.upsert_mapping("bob", "jira-1", telegram_display_name="")
        failures += _check(added, "upsert: invalid JSON => treat as empty => added=true")

        try:
            content = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            content = None
        failures += _check(isinstance(content, list), "upsert: users.json after write is valid JSON array")
        failures += _check(_jira_for_username(content, "bob") == "jira-1", "upsert: mapping exists after recover")
        rec_bob = _record_for_username(content, "bob")
        failures += _check(
            isinstance(rec_bob, dict) and rec_bob.get("telegram_id", "") == "",
            "upsert: default telegram_id empty string on disk",
        )

        tmp_path = p.with_name(f"{p.name}.tmp")
        failures += _check(not tmp_path.exists(), "upsert: tmp file should not remain after success")

    return failures


def main() -> int:
    failures = 0
    failures += test_get_jira_account_id_empty_and_invalid()
    failures += test_upsert_validation_and_no_overwrite_valid()
    failures += test_upsert_overwrite_invalid_value()
    failures += test_upsert_resilience_invalid_json_and_atomicity()

    if failures:
        print(f"PHASE 4 USERS STORE TEST FAILED with {failures} failure(s)")
        return 1
    print("PHASE 4 USERS STORE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
