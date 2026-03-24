# Phase 4: Users Store (`users.json`)

## 1. Mục tiêu
- Cung cấp lớp `UsersStore` chịu trách nhiệm:
  - đọc `users.json`
  - kiểm tra mapping tồn tại
  - upsert mapping khi user cung cấp `jira_account_id` lần đầu (kèm `user_name`, `telegram_display_name`)
  - đảm bảo write an toàn khi nhiều conversation cập nhật cùng lúc

## 2. Định dạng file (`users.json`)
- Root là **JSON array** `[]`, mỗi phần tử là object với **bốn key string**:
  - `user_name`: nhãn ưu tiên username (không `@`), không có thì họ tên hoặc `telegram_id` (do bot/handlers quyết định khi upsert).
  - `telegram_id`: id Telegram (string).
  - `telegram_display_name`: họ + tên hiển thị trên Telegram (`first_name` + `last_name`), có thể rỗng.
  - `jira_id`: `jira_account_id` đã trim.

- **Legacy:** file cũ dạng object `{ "telegram_id": "jira_id", ... }` vẫn được đọc và migrate trong memory; lần ghi sau (upsert) sẽ chuyển sang mảng. Các bản ghi migrate có `user_name` / `telegram_display_name` rỗng.

## 3. Contract API

### 3.1. `get_jira_account_id(telegram_account_id) -> jira_account_id | None`
- Trả về `None` nếu không có bản ghi khớp `telegram_id`, hoặc `jira_id` rỗng/invalid.
- Trả về `None` nếu `telegram_account_id` đầu vào rỗng/whitespace.

Quy ước “invalid” cho `jira_id`:
- Chỉ hợp lệ khi là **JSON string** và sau `trim()` **không rỗng**.

### 3.2. `upsert_mapping(telegram_account_id, jira_account_id, *, user_name="", telegram_display_name="") -> bool(added)`
- Nếu `jira_account_id` rỗng sau trim: no-op, `added = false`.
- Nếu `telegram_account_id` rỗng sau trim: no-op, `added = false`.
- Nếu `user_name` rỗng sau trim: lưu `user_name = telegram_id` (fallback).
- `telegram_display_name` được trim; cho phép chuỗi rỗng.

Hành vi mapping:
- Nếu đã có bản ghi với `telegram_id` đó và `jira_id` hợp lệ: **không ghi đè**, `added = false`.
- Nếu chưa có hoặc `jira_id` hiện tại không hợp lệ: ghi/cập nhật bản ghi, `added = true`.

### 3.3. `get_reverse_mapping() -> dict[jira_id, telegram_id]`
- Dùng cho Phase 5 reporter; logic chọn `telegram_id` nhỏ nhất khi nhiều Telegram trùng một Jira giữ nguyên.

## 4. Atomic write & concurrency (đặc biệt trên Windows)
- File lock khi ghi; lock bao trọn read/validate/write trong `upsert_mapping()`.
- Ghi `users.json.tmp` rồi `replace` sang `users.json`.
- Timeout lock ~5–10 giây; hết hạn hoặc lỗi IO: không ghi, `added = false`.

## 5. Validation & resilience
- File không tồn tại (khi `create_if_missing`): tạo `[]`.
- JSON lỗi: log, coi dữ liệu trống, upsert có thể recover.
- File rỗng/whitespace: coi trống.
- Root không phải `list` hoặc `dict` (legacy): coi trống.

## 6. Acceptance criteria
- Upsert không ghi đè `jira_id` hợp lệ đã có.
- Bản ghi `jira_id` rỗng/invalid: upsert được phép thay thế.
- Input rỗng/invalid: no-op, `added=false`.
- Lock timeout / write lỗi: không ghi, `added=false`.
- JSON sau ghi luôn hợp lệ (mảng object đủ field khi có ít nhất một bản ghi hợp lệ).
- Tránh race dễ mất mapping.
