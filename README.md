# Jira Chatbot Telegram

Bot Telegram kết nối **Jira Cloud** để tạo việc (issue + sub-task checklist + file đính kèm), lưu mapping người dùng Telegram ↔ Jira, và gửi **báo cáo định kỳ** theo hạn hoàn thành (sắp đến hạn / quá hạn) vào nhóm đã cấu hình.

## Tính năng chính

- **Giao việc** (`/giaoviec`): Admin project trên Jira mới được giao cho người khác; chọn assignee (reply / @mention / nhập `jira_account_id`), nhập summary, mô tả, file (tuỳ chọn), checklist (tuỳ chọn), số ngày due, xác nhận tạo issue trên Jira.
- **Việc của tôi** (`/vieccuatoi`): Tạo việc gán cho chính mình (luồng tương tự, không cần quyền admin project).
- **Hủy phiên**: `/huy` hoặc `/cancel` trong lúc đang điền form.
- **Hướng dẫn nhanh** (`/huongdan` hoặc `/help`): Trả về message cố định mô tả điều kiện sử dụng và danh sách lệnh.
- **Báo cáo định kỳ**: Theo `due.notification.report_times` và timezone trong config; gửi vào chat đầu tiên trong `allowed_chat_ids`.

Chi tiết kỹ thuật và contract nằm trong thư mục `[Documents/](Documents/)`.

## Chuẩn bị môi trường

- Python **3.11+** (khuyến nghị 3.12/3.13).
- Cài dependency (ví dụ):
  ```bash
  pip install python-telegram-bot apscheduler
  ```
  Trên Windows, nếu thiếu timezone `Asia/Ho_Chi_Minh`, có thể cài thêm: `pip install tzdata`.

## Cài đặt nhanh trên Windows

### 1. Clone repo và tạo môi trường ảo

```powershell
cd C:\dev\Chatbot
git clone https://github.com/hieuvt/jira_chatbot_tele.git JiraChatbotTele
cd .\JiraChatbotTele
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Nếu PowerShell chặn script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Cài thư viện

```powershell
python -m pip install --upgrade pip
pip install python-telegram-bot apscheduler tzdata
```

### 3. Tạo file cấu hình chạy thật

```powershell
Copy-Item .\config\config.example.json .\config\config.json
```

Sau đó mở `config/config.json` để điền:

- `telegram.bot_token`
- `telegram.allowed_chat_ids`
- `jira.base_url`, `jira.email`, `jira.api_token`
- `jira.project_key`, `jira.issue_type_id`, `jira.subtask_issue_type_id`

### 4. Chạy thử bot

```powershell
python .\src\bot\entrypoint.py
```

Nếu thấy log `Application started` là bot đã polling thành công.

## Chuẩn bị Jira (Jira Cloud)

1. **Tài khoản service** (email + [API token](https://id.atlassian.com/manage-profile/security/api-tokens)) dùng cho bot — không dùng token cá nhân của từng nhân viên cho thao tác bot.
2. **Quyền trên project** (`project_key` trong config):
  - Bot cần ít nhất quyền tương đương **Browse project** và **Create issues** (và quyền gán assignee / tạo sub-task theo cấu hình workflow của bạn).
  - Kiểm tra **membership**: user được giao việc phải là thành viên project (xuất hiện trong role actors của project).
3. **Admin project (chỉ cho `/giaoviec`)**
  Bot xác định “được giao việc cho người khác” nếu user đó thuộc **một project role có tên chứa `admin`** (không phân biệt hoa thường). Cấu hình role trên Jira cho đúng người được phép giao việc.
4. **Issue type ID** (bắt buộc dạng số ID trong Jira):
  - `issue_type_id`: loại issue cho **task chính**.
  - `subtask_issue_type_id`: loại issue cho **mỗi dòng checklist** (sub-task).  
   Lấy ID trong Jira (Project settings → Issue types, hoặc qua REST/API tùy môi trường).
5. `**base_url`**: URL site, ví dụ `https://ten-cong-ty.atlassian.net` (không có slash cuối).

## Chuẩn bị bot Telegram

1. Tạo bot qua [@BotFather](https://t.me/BotFather), lấy **HTTP API token**.
2. Thêm bot vào **nhóm / supergroup** cần dùng.
3. **Group Privacy** (BotFather → Bot Settings → Group Privacy):
  - Nếu bật *Privacy mode*, bot chỉ nhận lệnh và tin nhắn có mention/reply tùy chính sách Telegram. Bot này dùng **ForceReply** cho một số bước trong nhóm để người dùng trả lời — nên kiểm tra thực tế trên nhóm; nếu bot không nhận được tin nhắn thường, cân nhắc tắt Privacy hoặc dùng lệnh/reply đúng cách.
4. Lấy **chat id** của nhóm (số âm thường dạng `-100...`) và điền vào `telegram.allowed_chat_ids`.
  - Chat **đầu tiên** trong danh sách là nơi nhận **báo cáo định kỳ** Phase 5.

## Cấu hình: `config/config.json`

File thật **không commit** (đã có trong `.gitignore`). Sao chép từ `[config/config.example.json](config/config.example.json)`:


| Nhóm                             | Ý nghĩa                                                                                                                                            |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `telegram.bot_token`             | Token BotFather                                                                                                                                    |
| `telegram.allowed_chat_ids`      | Danh sách id nhóm; **phần tử đầu tiên** là chat nhận **báo cáo định kỳ**. (Handler hiện không chặn chat khác — chỉ nên thêm bot vào nhóm tin cậy.) |
| `telegram.attachments.max_files` | Tối đa số file mỗi phiên hội thoại                                                                                                                 |
| `jira.`*                         | `base_url`, `email`, `api_token`, `project_key`, `issue_type_id`, `subtask_issue_type_id`, `attachment_max_bytes`                                  |
| `jira.http` (tuỳ chọn)           | `timeout_seconds`, `retry_count`, `retry_backoff_seconds`                                                                                          |
| `due.notification`               | `window_days`, `report_timezone`, `report_times` (báo cáo định kỳ)                                                                                 |
| `conversation.timeout_minutes`   | Hết hạn phiên hội thoại nếu không tương tác                                                                                                        |


Chạy bot từ **thư mục gốc repo**:

```bash
python src/bot/entrypoint.py
```

## Tự chạy khi bật máy (Windows Task Scheduler)

Repo đã có sẵn:

- `run_bot.bat`: chạy bot từ đúng thư mục repo, ghi log vào `logs/startup-bot.log`.
- `scripts/windows/register_startup_task.ps1`: đăng ký task startup.

### 1. Đăng ký task (PowerShell chạy quyền Administrator)

```powershell
cd C:\dev\Chatbot\JiraChatbotTele
powershell -ExecutionPolicy Bypass -File .\scripts\windows\register_startup_task.ps1 -TaskName "JiraTelegramBot" -PythonExe "C:\Python313\python.exe"
```

Ghi chú:

- Task được tạo với trigger **AtStartup**.
- Chế độ chạy nền: **Run whether user is logged on or not**.
- Nếu đã có task cùng tên, script sẽ ghi đè (`-Force`).

### 2. Chạy thử ngay không cần reboot

```powershell
Start-ScheduledTask -TaskName "JiraTelegramBot"
```

### 3. Kiểm tra trạng thái

- Mở Task Scheduler và xem `Last Run Result` (mã `0x0` là thành công).
- Xem log runtime:

```powershell
Get-Content .\logs\startup-bot.log -Tail 100
```

### 4. Gỡ task khi không dùng

```powershell
Unregister-ScheduledTask -TaskName "JiraTelegramBot" -Confirm:$false
```

### Checklist verify sau khi cài

1. Đăng ký task thành công bằng script PowerShell.
2. `Start-ScheduledTask` chạy được, bot khởi động và log có dòng `Starting JiraTelegramBot`.
3. Reboot máy, task tự chạy lại sau khi máy lên.
4. `Last Run Result` không lỗi và log không có traceback mới.

## Cấu hình: `config/templates.json`

- `**user_inputs.intent_aliases**`: lệnh khởi đầu (mặc định `/giaoviec`, `/vieccuatoi`). Intent khớp **đúng chuỗi** sau khi normalize (thường là viết thường).
- `**bot_replies`**: toàn bộ câu trả lời cố định (`TPL_*`). Giữ nguyên key nếu chỉ sửa nội dung tiếng Việt; đổi key cần đồng bộ code.
- Mặc định có thêm intent trợ giúp với alias: `/huongdan`, `/help` (`HELP` -> `TPL_HELP`).

File mẫu: `[config/templates.json](config/templates.json)`.

## Dữ liệu cục bộ: `data/users.json`

- Lưu mapping **Telegram user** ↔ `**jira_account_id` (accountId Jira Cloud)**.
- Định dạng chuẩn: **mảng** các object `user_name`, `telegram_id`, `telegram_display_name`, `jira_id`.
- File nằm trong `.gitignore`; bot có thể **tự tạo** file khi có upsert lần đầu. Nên backup khi deploy.

## Hướng dẫn sử dụng

### 1. Tạo nhóm và thành viên

- Tạo nhóm Telegram, thêm bot và các thành viên làm việc trên Jira.
- Đảm bảo `allowed_chat_ids` khớp nhóm đó.
- Mỗi người khi dùng lần đầu có thể được bot yêu cầu nhập `**jira_account_id`** để lưu vào `users.json` (không ghi đè mapping hợp lệ đã có).

### 2. Giao việc — `/giaoviec`

1. Gửi lệnh `/giaoviec` (trong nhóm có thể cần `/giaoviec@TenBot`).
2. Bot kiểm tra bạn là **admin project** trên Jira (theo role có chữ `admin`).
3. Chọn người được giao: **reply** tin nhắn của họ, **@mention**, hoặc nhập trực tiếp `jira_account_id`. Nếu họ chưa có mapping, bot sẽ hỏi `jira_account_id` của họ.
4. Nhập **tiêu đề** (summary) → **mô tả** (description).
5. **File đính kèm**: upload nếu cần; khi xong nhập `Xong` / `Done`; bỏ qua nhập `Không` / `No`.
6. **Checklist**: mỗi dòng một mục; `Xong` để kết thúc; `Không` để bỏ qua (tối đa 20 mục).
7. Nhập **số ngày** hoàn thành (số nguyên dương) — due date tính từ thời điểm tạo.
8. **Xác nhận**: `Có` / `Yes` / `Co` để tạo issue; `Không` / `No` để hủy phiên.

### 3. Giao cho tôi — `/giaochotoi`

Luồng giống giao việc nhưng assignee là **chính bạn**; không cần quyền admin project. Vẫn cần là **thành viên project** trên Jira.

### 4. Hủy giữa chừng

- Gửi `**/huy`** hoặc `**/cancel**` (hoặc từ tương đương đã chuẩn hoá trong code) để kết thúc phiên và nhận template `TPL_CANCELLED`.
- Ở bước xác nhận, trả lời `**Không**` cũng hủy tạo việc.

### 5. Việc của tôi — `/vieccuatoi`

Thành viên tự kiểm tra công việc của chính mình

### 5. Xem hướng dẫn nhanh

- Gửi `**/huongdan**` hoặc `**/help**` để bot trả về nội dung hướng dẫn sử dụng cố định.

Trong **supergroup**, một số bước bot gửi kèm **ForceReply** để bạn trả lời đúng luồng.

Các intent khởi đầu được cấu hình trong `templates.json` (mặc định gồm `/giaoviec`, `/giaochotoi`, `/vieccuatoi`, `/huongdan`, `/help`); tin khác khi không trong phiên sẽ nhận template “chưa hiểu yêu cầu”.

## Kiểm thử nhanh (tuỳ chọn)

Trong thư mục `[scripts/](scripts/)` có các script smoke/negative cho Jira client, state machine, users store, reporter (một số cần `config/config.json` và mạng tới Jira). Xem từng file docstring ở đầu script.

## Giấy phép & đóng góp

Thêm theo nhu cầu dự án của bạn.