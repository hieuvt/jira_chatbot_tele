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

### 2.2. `upsert_mapping(telegram_account_id, jira_account_id) -> bool(added)`
- Nếu `telegram_account_id` chưa tồn tại:
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
- Cơ chế write atomic:
  - ghi ra file tạm (`users.json.tmp`)
  - rename/replace sang `users.json` trong cùng filesystem.
- Retry nếu gặp lock contention.

## 4. Validation & resilience
- Khi load file:
  - Nếu `users.json` không tồn tại: tạo file rỗng theo format ({}).
  - Nếu file JSON lỗi: báo log ops (và bot có thể disable upsert cho đến khi config đúng).

## 5. Acceptance criteria
- Upsert không ghi đè mapping đã tồn tại.
- Ghi file không làm hỏng JSON.
- Không race condition dễ gây mất mapping.

