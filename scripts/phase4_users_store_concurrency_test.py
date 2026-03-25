"""Test đồng thời UsersStore và timeout lock.

Usage:
  python scripts/phase4_users_store_concurrency_test.py
"""

from __future__ import annotations

import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


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


def test_concurrent_upsert_single_key() -> int:
    """Many threads upsert same mapping simultaneously.

    Expectation:
    - file ends up with one valid mapping
    - only one call returns added=true
    """

    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"
        store = UsersStore(p)

        username_key = "concurrentuser"
        candidates = ["jira-a", "jira-b", "jira-c", "jira-d", "jira-e"]

        results: list[bool] = []
        added_count = 0

        def worker(i: int) -> bool:
            s = UsersStore(p)  # separate instance -> tests lock is cross-instance
            return s.upsert_mapping(
                username_key,
                candidates[i % len(candidates)],
                telegram_display_name="",
            )

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(worker, i) for i in range(25)]
            for f in as_completed(futures):
                v = bool(f.result())
                results.append(v)
                if v:
                    added_count += 1

        failures += _check(p.exists(), "concurrency: users.json created")
        failures += _check(added_count == 1, f"concurrency: exactly one added=true (got {added_count})")

        mapped = store.get_jira_account_id(username_key)
        failures += _check(mapped is not None and mapped in candidates, "concurrency: stored mapping is one candidate")

    return failures


def test_lock_timeout_no_write() -> int:
    """Hold lock in one thread longer than timeout in another.

    Expectation:
    - upsert should fail with added=false
    - file mapping should remain absent (or untouched)
    """

    failures = 0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "users.json"

        store1 = UsersStore(p)
        store1_lock_started = threading.Event()
        keep_lock_for = 1.2

        def holder() -> None:
            with store1._acquire_lock():  # noqa: SLF001
                store1_lock_started.set()
                time.sleep(keep_lock_for)

        t = threading.Thread(target=holder, daemon=True)
        t.start()

        if not store1_lock_started.wait(timeout=3.0):
            print("[FAIL] lock timeout: holder did not acquire lock in time")
            return 1

        store2 = UsersStore(p)
        # shorten timeout to make test fast
        store2._LOCK_TIMEOUT_SECONDS = 0.4  # noqa: SLF001

        added = store2.upsert_mapping("timeoutuser", "jira-timeout", telegram_display_name="")
        failures += _check(not added, "lock timeout: upsert returns added=false when lock not acquired")

        # Should not have written mapping
        mapped = store2.get_jira_account_id("timeoutuser")
        failures += _check(mapped is None, "lock timeout: mapping remains absent after timeout no-op")

        t.join(timeout=3.0)

    return failures


def main() -> int:
    failures = 0
    failures += test_concurrent_upsert_single_key()
    failures += test_lock_timeout_no_write()

    if failures:
        print(f"PHASE 4 USERS STORE CONCURRENCY TEST FAILED with {failures} failure(s)")
        return 1
    print("PHASE 4 USERS STORE CONCURRENCY TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

