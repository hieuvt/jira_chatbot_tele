# Phase 3 Test Scripts

## 1) Compile check

```powershell
python -m py_compile src/conversation/intents.py src/conversation/validators.py src/conversation/state_machine.py src/bot/handlers.py src/bot/entrypoint.py
```

## 2) Smoke test (state-machine end-to-end with fakes)

```powershell
python scripts/phase3_smoke_test.py
```

Mục tiêu:
- Chạy full flow `việc của tôi` (có attachment + checklist + confirm tạo việc).
- Chạy flow `giao việc` với assignee chưa mapping, nhập `jira_account_id` bổ sung.

## 3) Negative tests

```powershell
python scripts/phase3_negative_test.py
```

Mục tiêu:
- Unknown intent.
- Invalid `due_days`.
- Member không có quyền admin khi `giao việc`.
- Giới hạn attachment (size và max files).
- Timeout session.
- Mapping lỗi `JiraClientError.code` -> bot message.

## 4) Scenario runner (JSON-driven)

```powershell
python scripts/phase3_scenario_runner.py --scenario-file scripts/phase3_scenarios.example.json
```

Tuỳ chọn:

```powershell
python scripts/phase3_scenario_runner.py --scenario-file scripts/phase3_scenarios.example.json --stop-on-fail
```

Mục tiêu:
- Chạy nhiều kịch bản theo file JSON, không cần sửa code script.
- Mỗi step có thể là `text`, `reply`, `attachment`, `set_timeout`.
- Assertion hỗ trợ:
  - `expect_contains`
  - `expect_exact`
