"""Chạy kịch bản state machine từ file JSON (bước + assert).

Usage:
  python scripts/phase3_scenario_runner.py --scenario-file scripts/phase3_scenarios.example.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from phase3_test_common import build_state_machine, make_attachment, make_reply, make_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3 state-machine scenarios from JSON.")
    parser.add_argument(
        "--scenario-file",
        default="scripts/phase3_scenarios.example.json",
        help="Path to scenario JSON file.",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop immediately when first assertion fails.",
    )
    return parser.parse_args()


def _configure_stdout_for_unicode() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        except Exception:
            pass


def _load_json(path: str) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("Scenario file must be a JSON object.")
    return payload


def _to_bytes(raw: str, encoding: str = "utf-8") -> bytes:
    return raw.encode(encoding)


def _run_step(machine: object, step: dict[str, Any], runtime: dict[str, Any]) -> str:
    action = str(step.get("action", "")).strip().lower()
    chat_id = int(step.get("chat_id", runtime["default_chat_id"]))
    user_id = int(step.get("user_id", runtime["default_user_id"]))
    default_su = runtime.get("default_sender_username")
    if isinstance(default_su, str):
        default_su = default_su.strip() or None
    else:
        default_su = None

    if action == "text":
        text = str(step.get("text", ""))
        su = step.get("sender_username", default_su)
        su_s = str(su).strip() if su is not None else ""
        return machine.handle_message(
            make_text(chat_id, user_id, text, sender_username=su_s or None)
        )

    if action == "reply":
        reply_to_user_id = int(step["reply_to_user_id"])
        text = str(step.get("text", ""))
        su = step.get("sender_username", default_su)
        su_s = str(su).strip() if su is not None else ""
        rtu = step.get("reply_to_username")
        rtu_s = str(rtu).strip().lower() if rtu is not None and str(rtu).strip() else None
        return machine.handle_message(
            make_reply(
                chat_id,
                user_id,
                reply_to_user_id,
                text=text,
                reply_to_username=rtu_s,
                sender_username=su_s or None,
            )
        )

    if action == "attachment":
        filename = str(step.get("filename", "file.txt"))
        content = _to_bytes(str(step.get("content", "test")))
        size = int(step.get("size", len(content)))
        return machine.handle_message(make_attachment(chat_id, user_id, filename, size, content))

    if action == "set_timeout":
        delta_minutes = int(step.get("minutes", 11))
        key = (chat_id, user_id)
        session = machine._sessions.get(key)  # noqa: SLF001
        if not session:
            return "__NO_SESSION__"
        session.updated_at = datetime.now(timezone.utc) - timedelta(minutes=delta_minutes)
        return "__TIMEOUT_SET__"

    raise ValueError(f"Unsupported step action: {action}")


def _assert_output(output: str, step: dict[str, Any]) -> tuple[bool, str]:
    expected_contains = step.get("expect_contains")
    expected_exact = step.get("expect_exact")
    if expected_contains is not None:
        text = str(expected_contains)
        ok = text in output
        return ok, f'expect_contains="{text}"'
    if expected_exact is not None:
        text = str(expected_exact)
        ok = output == text
        return ok, f'expect_exact="{text}"'
    return True, "no assertion"


def _safe_printable(text: str) -> str:
    encoding = str(getattr(sys.stdout, "encoding", "") or "utf-8")
    try:
        text.encode(encoding)
        rendered = text
    except UnicodeEncodeError:
        rendered = text.encode("ascii", errors="backslashreplace").decode("ascii")
    return rendered


def run_scenario(scenario: dict[str, Any], *, stop_on_fail: bool) -> tuple[int, int]:
    name = str(scenario.get("name", "unnamed_scenario"))
    default_chat_id = int(scenario.get("default_chat_id", 9001))
    default_user_id = int(scenario.get("default_user_id", 9001))
    user_mapping = scenario.get("user_mapping", {})
    member_ids = set(scenario.get("member_ids", []))
    admin_ids = set(scenario.get("admin_ids", []))
    if not isinstance(user_mapping, dict):
        raise ValueError(f"Scenario '{name}' user_mapping must be object.")
    machine, _, _ = build_state_machine(
        user_mapping={str(k): str(v) for k, v in user_mapping.items()},
        member_ids={str(item) for item in member_ids},
        admin_ids={str(item) for item in admin_ids},
        require_proof_photo_on_mark_done_override=False,
    )
    dsu = scenario.get("default_sender_username")
    default_sender_username: str | None = str(dsu).strip() if dsu is not None and str(dsu).strip() else None
    runtime = {
        "default_chat_id": default_chat_id,
        "default_user_id": default_user_id,
        "default_sender_username": default_sender_username,
    }
    steps = scenario.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError(f"Scenario '{name}' steps must be array.")

    total = 0
    failed = 0
    print(f"[scenario] {name}")
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Scenario '{name}' step #{index} must be object.")
        output = _run_step(machine, raw_step, runtime)
        ok, rule_text = _assert_output(output, raw_step)
        total += 1
        if ok:
            print(f"  [OK] step {index}: {_safe_printable(rule_text)}")
        else:
            failed += 1
            print(f"  [FAIL] step {index}: {_safe_printable(rule_text)}")
            print(f"    output: {_safe_printable(output)}")
            if stop_on_fail:
                break
    return total, failed


def main() -> int:
    _configure_stdout_for_unicode()
    args = parse_args()
    payload = _load_json(args.scenario_file)
    scenarios = payload.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("'scenarios' must be array.")
    if not scenarios:
        raise ValueError("No scenarios found.")

    total_steps = 0
    total_failures = 0
    for item in scenarios:
        if not isinstance(item, dict):
            raise ValueError("Each scenario must be object.")
        count, failures = run_scenario(item, stop_on_fail=args.stop_on_fail)
        total_steps += count
        total_failures += failures

    print(f"TOTAL STEPS: {total_steps}")
    print(f"TOTAL FAILURES: {total_failures}")
    if total_failures:
        print("PHASE 3 SCENARIO RUNNER FAILED")
        return 1
    print("PHASE 3 SCENARIO RUNNER PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
