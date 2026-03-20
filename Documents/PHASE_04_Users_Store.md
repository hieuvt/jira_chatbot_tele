# Phase 4: Users Store (`users.json`)

## 1. Mục tiêu
- Cung cấp lớp `UsersStore` chịu trách nhiệm:
  - đọc `users.json`
  - kiểm tra mapping tồn tại
  - upsert mapping khi user cung cấp `jira_account_id` lần đầu
  - đảm bảo write an toàn khi nhiều conversation cập nhật cùng lúc

## 2. Contract API
### 2.1. `get_jira_account_id(telegram_account_id) -> jira_account_id | None`
- Trả về `None` nếu:
  - key không tồn tại
  - value rỗng/invalid
- Trả về `None` nếu `telegram_account_id` đầu vào rỗng/whitespace.

Quy ước “invalid”:
- Value trong `users.json` chỉ được coi là hợp lệ khi là **JSON string** và sau `trim()` **không rỗng**.
- Nếu value **không phải string** hoặc sau `trim()` rỗng thì coi là invalid.

### 2.2. `upsert_mapping(telegram_account_id, jira_account_id) -> bool(added)`
- Nếu `jira_account_id` rỗng/whitespace/invalid:
  - không ghi file
  - trả `added = false` (no-op)
- Nếu `telegram_account_id` rỗng/whitespace:
  - không ghi file
  - trả `added = false` (no-op)

Quy ước:
- `jira_account_id` sẽ được `trim()` trước khi validate và lưu.
- Nếu sau `trim()` mà `jira_account_id` rỗng thì coi là invalid.
- Value “invalid” trong file: không phải JSON string hoặc sau `trim()` rỗng.

- Nếu `telegram_account_id` **chưa tồn tại** hoặc **đang tồn tại nhưng value rỗng/invalid**:
  - ghi mapping mới
  - trả `added = true`
- Nếu đã tồn tại:
  - giữ nguyên (mặc định)
  - trả `added = false`

## 3. Atomic write & concurrency (đặc biệt trên Windows)
Vấn đề cần xử lý:
- Hai user/2 request cùng lúc có thể ghi đè.

Giải pháp thiết kế (khuyến nghị):
- File lock khi ghi (dựa trên library lock file tương thích Windows).
- Giữ lock bao trọn read/validate/write trong toàn bộ luồng `upsert_mapping()` để tránh lost update.
- Cơ chế write atomic:
  - ghi ra file tạm (`users.json.tmp`)
  - rename/replace sang `users.json` trong cùng filesystem.
- Chính sách lock: chờ lấy lock (blocking) + retry nếu gặp lock contention, **tối đa ~5-10 giây**; hết thời gian chờ thì coi là thất bại (fail).
  - Trong trường hợp fail vì lock timeout: `upsert_mapping()` không ghi gì và trả `added = false`.
  - Trong trường hợp write/replace thất bại (IO error/permission lỗi): `upsert_mapping()` không ghi gì và trả `added = false`.

## 4. Validation & resilience
- Khi load file:
  - Nếu `users.json` không tồn tại: tạo file rỗng theo format ({}).
  - Nếu file JSON lỗi:
    - báo log ops
    - coi như dữ liệu trống và cho phép upsert (recover bằng cách bot rewrite file đúng format).
  - Nếu file rỗng/whitespace: coi như dữ liệu trống (`{}`).
  - Nếu JSON parse được nhưng root không phải object/dict: coi như dữ liệu trống (`{}`).

## 5. Acceptance criteria
- Upsert không ghi đè mapping đã tồn tại (hợp lệ).
- Trường hợp file có key nhưng value rỗng/invalid: upsert được phép ghi đè (coi như chưa có mapping hợp lệ).
- Trường hợp `jira_account_id` đầu vào rỗng/invalid: upsert không ghi gì (no-op) và trả `added=false`.
- Trường hợp không lấy được lock trong ~5-10 giây hoặc write/replace thất bại: upsert không ghi gì và trả `added=false`.
- Ghi file không làm hỏng JSON.
- Không race condition dễ gây mất mapping.

