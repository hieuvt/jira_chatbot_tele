# Phase 1: Project Skeleton (No Business Logic)

## 1. Mục tiêu
- Tạo bộ khung Python để các phase sau plug-in logic nghiệp vụ một cách sạch.
- Chuẩn hóa cách tổ chức modules, dependency, và cách chạy bot + scheduler.

## 2. Cấu trúc thư mục (khớp repo hiện tại)
```text
config/
  config.json                   # cấu hình chạy thật (không commit secret)
  config.example.json
  templates.json                # bot_replies + intent_aliases
data/
  users.json                    # mapping (thường mount volume)
src/
  bot/
    entrypoint.py                # bootstrap: config, Jira, state machine, Reporter, scheduler, polling
    handlers.py                  # đăng ký handlers, build MessageInput
  scheduler/
    jobs.py                      # APScheduler: cron theo report_times
  conversation/
    intents.py                   # alias -> Intent enum
    state_machine.py             # luồng hội thoại
    validators.py
    templates.py                 # load templates.json
  jira/
    client.py
    models.py
    permissions.py
  reports/
    reporter.py                  # Phase 5: build_report + build_report_messages + send_report
  storage/
    users_store.py
  config/
    schema.md                    # mô tả field config
  common/
    logging.py
    errors.py
scripts/                        # phase smoke tests (phase2–5, …)
Documents/                      # plan theo phase
```

## 3. Contracts module (định nghĩa mức interface)
### 3.1. Intent Router
- Đầu vào: message text + sender info (telegram_account_id).
- Đầu ra: intent enum (`giao_viec`, `viec_cua_toi`, `help`, `unknown`) + payload.
- Quy tắc:
  - `unknown` -> reply template “giới thiệu lại nhập đúng intent”.

### 3.2. Conversation State Machine
- Mỗi state chịu trách nhiệm:
  - validate input,
  - lưu tạm dữ liệu conversation (summary/description/checklist/dueDays/files).
  - chuyển sang state tiếp theo.
- Policy skeleton (Phase 1): state in-memory sẽ được reset nếu user không tương tác trong 15 phút.

### 3.3. Jira Client
- Chỉ định nghĩa “đường đi” gọi REST (không implement sâu ở phase này):
  - `check_project_membership(jira_account_id, project_key) -> bool`
  - `check_project_admin(jira_account_id, project_key) -> bool`
  - `create_issue(request) -> issue_key/id`
  - `create_subtasks(parent_issue_key, checklist_items) -> list of subtask keys`
  - `upload_attachments(issue_key, files) -> attachment results`

### 3.4. Users Store
- Hàm hợp đồng:
  - `get_jira_account_id(telegram_account_id) -> jira_account_id | None`
  - `upsert_mapping(telegram_account_id, jira_account_id, *, user_name=..., telegram_display_name=...) -> bool(added)`
  - atomic write/lock được định nghĩa để phase sau implement.

### 3.5. Reporter (Phase 5 — đã nối vào entrypoint)
- `build_report(window_days, now) -> ReportModel` — query Jira, nhóm assignee, lọc theo `users.json`, tách quá hạn / sắp đến hạn.
- `build_report_messages(window_days, now) -> list[str]` — block tổng + một message / assignee; HTML (link Jira, dòng Assignee).
- `send_report(telegram_chat_id, message_texts)` — gửi tuần tự qua Bot API (`parse_mode="HTML"`).
- Các hàm `get_due_tasks` / `render_report` legacy trong file reporter có thể giữ stub; luồng chính dùng các API trên.

## 4. Non-functional requirements
- Logging có correlation id theo conversation (telegram chat id + sender id + timestamp).
- Logging tối thiểu (Phase 1): `chat_id`, `telegram_user_id`, `intent`, `state`, `correlation_id`, `timestamp`.
- Error taxonomy:
  - `JiraAuthError` -> nhắn user/ops hướng dẫn kiểm tra credentials (không rò rỉ token).
  - `JiraPermissionError` -> nhắn đúng template member/admin.
  - `ValidationError` -> nhắc người dùng nhập đúng format (ví dụ DueDays phải là số).

## 5. Acceptance criteria
- Bot có thể start và nhận message.
- Intent router trả về đúng intent enum theo alias trong `templates.json`.
- Templates được tải từ `config/templates.json` và lookup đúng.
- Scheduler `APScheduler` được start trong `entrypoint` theo `due.notification.report_times` (Phase 5 gắn job gọi Jira + Reporter thật).
- `JiraClient` / `Reporter` là implementation đầy đủ ở phase sau; skeleton ban đầu đã được thay bằng logic thật khi hoàn tất Phase 2–5.

## 6. Lựa chọn & khuyến nghị mặc định (Phase 1)
Các quyết định sau được coi là mặc định cho Phase 1:
- Telegram update mode: `python-telegram-bot` chạy theo **long polling** (`run_polling`) để triển khai nhanh cho MVP.
- Conversation state/key: lưu **in-memory** theo `(chat_id, telegram_user_id)` trong Phase 1 (mất khi restart). Nếu cần bền vững, sẽ chuyển sang persist ở phase sau.
- Conversation timeout: reset state sau **15 phút** không hoạt động.
- Huỷ flow: user gõ `Hủy` -> reset state ngay (không hỏi xác nhận).
- Conversation buffer schema (in-memory) tối thiểu gồm các field theo flow: `summary`, `description`, `checklist_items`, `due_days`, `attachments`.
- Scheduler: dùng **`APScheduler`** để cấu hình job 2 lần/ngày (stub). Scheduler được start ngay khi bot boot và dùng timezone `Asia/Ho_Chi_Minh`.
- Templates: load từ `config/templates.json` — `bot_replies` (keys `TPL_*`) và `user_inputs.intent_aliases` (map tới `ASSIGN_TASK` / `MY_TASK`). Intent mặc định: `/giaoviec`, `/vieccuatoi`.
- File upload (Phase 1): chỉ lưu `file_meta` tối thiểu để phase sau upload lên Jira, gồm `filename`, `size_bytes`, `telegram_file_id`. Phase 1 chưa enforce limit/quotas.

