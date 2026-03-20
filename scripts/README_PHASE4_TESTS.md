# Phase 4: Users Store Tests

## 1) Chạy bằng script (không cần Telegram/Jira)

### 1.1 Test validate + resilience + atomic write
```powershell
python scripts/phase4_users_store_test.py
```

Mục tiêu:
- `get_jira_account_id()` trả `None` khi key không tồn tại / value rỗng/invalid.
- `upsert_mapping()` no-op khi input rỗng/invalid.
- Không overwrite mapping hợp lệ đã tồn tại.
- Cho phép overwrite khi value trong file là rỗng/invalid.
- Khi `users.json` là JSON lỗi: upsert vẫn recover và `users.json` sau cùng là JSON hợp lệ.
- Kiểm tra `users.json.tmp` không còn sau upsert thành công.

### 1.2 Test concurrency + lock timeout
```powershell
python scripts/phase4_users_store_concurrency_test.py
```

Mục tiêu:
- Nhiều thread upsert cùng 1 key: đảm bảo chỉ 1 lần trả `added=true`, và file cuối cùng có 1 mapping hợp lệ.
- Lock timeout: thread giữ lock lâu hơn timeout khiến thread còn lại fail (no write) và mapping không xuất hiện.

## 2) Kiểm tra bằng Telegram (manual)

Chuẩn bị:
- Chạy bot bình thường (`src/bot/entrypoint.py`).
- Mở `data/users.json` để theo dõi thay đổi (khuyến nghị backup file trước khi thử).

### 2.1 Kiểm tra “add mapping khi user mới”
1. Dùng một Telegram user **chưa có** `telegram_user_id` trong `data/users.json`.
2. Gửi `/giaoviec` (hoặc `/vieccuatoi`).
3. Bot sẽ hỏi bạn nhập `jira_account_id`.
4. Gửi vào một giá trị như `jira-user-123`.
5. Kiểm tra `data/users.json`:
   - Có key đúng `telegram_user_id` (dạng string).
   - Value đúng `jira_account_id` bạn vừa nhập.

### 2.2 Kiểm tra “không overwrite mapping hợp lệ”
1. Với cùng Telegram user ở bước 2.1, gửi lại `/giaoviec` (hoặc `/vieccuatoi`).
2. Khi bot đã biết mapping, nó **không nên** hỏi lại `jira_account_id`.
3. Nếu bạn vẫn cố gửi một `jira_account_id` khác trong quá trình hội thoại, mapping **không nên bị đổi** trong `data/users.json`.

### 2.3 Kiểm tra “overwrite khi mapping trong file invalid”
1. Dừng bot.
2. Sửa `data/users.json`: đặt value của key Telegram user đó thành `""` hoặc `"   "` (hoặc một value không phải string).
3. Khởi động lại bot.
4. Gửi `/giaoviec` (hoặc `/vieccuatoi`) với Telegram user đó.
5. Bot sẽ lại yêu cầu nhập `jira_account_id`.
6. Gửi `jira_account_id` mới và kiểm tra value trong `data/users.json` đã bị thay thế.

### 2.4 Nhóm / supergroup và Bot Privacy (quan trọng)
- Mặc định bot **không nhận** tin nhắn thường trong nhóm (chỉ lệnh `/...`, reply tới bot, hoặc `@mention` bot).
- Bot gắn **ForceReply** khi trả lời trong nhóm để client nhắc bạn **reply** tin bot — khi đó bước nhập `jira_account_id` (và các bước text sau) mới tới được bot.
- Tuỳ chọn: BotFather → Bot Settings → **Group Privacy** → **Turn off** để bot nhận mọi tin trong nhóm (cân nhắc spam).

