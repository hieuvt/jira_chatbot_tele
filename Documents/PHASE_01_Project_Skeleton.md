# Phase 1: Project Skeleton (No Business Logic)

## 1. Mục tiêu
- Tạo bộ khung Python để các phase sau plug-in logic nghiệp vụ một cách sạch.
- Chuẩn hóa cách tổ chức modules, dependency, và cách chạy bot + scheduler.

## 2. Đề xuất cấu trúc thư mục
```text
src/
  bot/
    entrypoint.py                # khởi chạy Telegram bot
    handlers.py                  # đăng ký handlers theo intent/state
  scheduler/
    jobs.py                      # stub job runner 2 lần/ngày (bootstrap trong entrypoint ở phase sau)
  conversation/
    intents.py                   # mapping text -> intent enum
    state_machine.py            # definitions cho state transitions
    validators.py               # parse/validate Summary/Description/DueDays/Checklist
    templates.py                # toàn bộ text template cố định
  jira/
    client.py                    # Jira REST client abstraction
    models.py                    # DTO: IssueCreateRequest, SubtaskCreateRequest,...
    permissions.py              # membership/admin checks interface
  reports/
    reporter.py                 # query + group + render message report
  storage/
    users_store.py             # đọc/ghi users.json + atomic write contract
  config/
    schema.md                   # mô tả config fields (không code)
  common/
    logging.py                 # logging setup contract
    errors.py                  # error taxonomy để bot reply đúng template
data/
  users.json                    # mapping gốc (thường mounted từ volume)
config/
  config.example.json
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
  - `upsert_mapping(telegram_account_id, jira_account_id) -> bool(added)`
  - atomic write/lock được định nghĩa để phase sau implement.

### 3.5. Reporter
- Hàm hợp đồng:
  - `get_due_tasks(window_days, now) -> issues grouped by assignee`
  - `render_report(issues) -> message_text`
  - `send_report(telegram chat id, message_text)`

## 4. Non-functional requirements
- Logging có correlation id theo conversation (telegram chat id + sender id + timestamp).
- Logging tối thiểu (Phase 1): `chat_id`, `telegram_user_id`, `intent`, `state`, `correlation_id`, `timestamp`.
- Error taxonomy:
  - `JiraAuthError` -> nhắn user/ops hướng dẫn kiểm tra credentials (không rò rỉ token).
  - `JiraPermissionError` -> nhắn đúng template member/admin.
  - `ValidationError` -> nhắc người dùng nhập đúng format (ví dụ DueDays phải là số).

## 5. Acceptance criteria
- Bot có thể start và nhận message (chưa cần tạo Jira issue).
- Intent router trả về đúng intent enum.
- Templates được tải từ file JSON ngoài và lookup đúng.
- Scheduler được bootstrapped bằng `APScheduler` để chạy 2 lần/ngày (stub, chưa query Jira).
- Có stub Jira client và stub reporter để phase sau replace logic.

## 6. Lựa chọn & khuyến nghị mặc định (Phase 1)
Các quyết định sau được coi là mặc định cho Phase 1:
- Telegram update mode: `python-telegram-bot` chạy theo **long polling** (`run_polling`) để triển khai nhanh cho MVP.
- Conversation state/key: lưu **in-memory** theo `(chat_id, telegram_user_id)` trong Phase 1 (mất khi restart). Nếu cần bền vững, sẽ chuyển sang persist ở phase sau.
- Conversation timeout: reset state sau **15 phút** không hoạt động.
- Huỷ flow: user gõ `Hủy` -> reset state ngay (không hỏi xác nhận).
- Conversation buffer schema (in-memory) tối thiểu gồm các field theo flow: `summary`, `description`, `checklist_items`, `due_days`, `attachments`.
- Scheduler: dùng **`APScheduler`** để cấu hình job 2 lần/ngày (stub). Scheduler được start ngay khi bot boot và dùng timezone `Asia/Ho_Chi_Minh`.
- Templates: load từ file JSON ngoài `config/templates.json` theo schema **fixed keys theo step/state** (load 1 lần lúc boot). Ví dụ keys: `unknown_intent`, `giao_viec.ask_summary`, `giao_viec.ask_due_days`, `viec_cua_toi.ask_description`.
- File upload (Phase 1): chỉ lưu `file_meta` tối thiểu để phase sau upload lên Jira, gồm `filename`, `size_bytes`, `telegram_file_id`. Phase 1 chưa enforce limit/quotas.

