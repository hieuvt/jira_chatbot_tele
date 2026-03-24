# Phase 5: Scheduler & Reporter (2 lần/ngày)

## 1. Mục tiêu
- Chạy job định kỳ theo cấu hình:
  - Timezone / report_timezone: `due.notification.report_timezone` (default `Asia/Ho_Chi_Minh`)
  - Times: `due.notification.report_times` — danh sách giờ `HH:MM` (mặc định `["08:00", "17:00"]`; có thể thêm bớt, ví dụ 3 lần/ngày)
- Mỗi lần chạy:
  - Query Jira lấy các issue theo `duedate`
  - Tách 2 nhóm:
    - “Quá hạn”: `duedate` < `today` (tính theo timezone report)
    - “Sắp đến hạn”: `duedate` trong `[today, today+N]` (inclusive, gồm cả `today`)
  - N: lấy theo `due.notification.window_days`
  - Group kết quả theo `assignee.accountId`
  - Filter assignee theo mapping Telegram từ `data/users.json` (chỉ cần assignee có mapping telegram; không gọi Telegram API để check membership group).
  - Nếu issue `assignee` null/không có `accountId`: đưa vào nhóm `Unassigned` và vẫn render trong report (không áp filter mapping Telegram cho `Unassigned`).
  - Gửi message báo cáo vào **1** chat/group (chat đầu tiên) trong `config.telegram.allowed_chat_ids` theo template cố định.

## 2. Query strategy (contract)
### 2.1. “Quá hạn”
- Điều kiện: `duedate` < `today`
- Không có lower bound (report toàn bộ issue overdue trong phạm vi project).
- Lưu ý: do `duedate` là ngày (không có giờ), so sánh dựa trên `today` theo `due.notification.report_timezone`.

### 2.2. “Sắp đến hạn”
- Điều kiện theo window (inclusive):
 - `duedate` nằm trong khoảng `[today, today+N]`

### 2.3. Pagination & rate limit
- Dự trù Jira có thể có nhiều issue:
  - dùng pagination (startAt/maxResults)
  - retry khi gặp rate limit (HTTP 429) theo backoff

### 2.4 JQL filter tối thiểu
- Không lọc theo `reporter` (vì report gom theo `assignee`).
- Chỉ lọc theo:
  - `project_key`
  - `duedate` không rỗng
  - `duedate <= (today + N)` để giảm dữ liệu query (các issue ngoài window sẽ được phân luồng tiếp theo trong Reporter).
- Không filter theo `issue_type_id`/`subtask_issue_type_id` (tính toàn bộ issue trong project, rồi phân luồng theo `duedate`).
- Không filter theo `status` (bao gồm cả Done/Closed nếu Jira vẫn còn `duedate`).

## 3. Dữ liệu hiển thị trong report
- Với mỗi assignee (có mapping Telegram trong `users.json`):
  - Danh sách issue: issue key (link HTML tới Jira nếu có `base_url`) + summary + `(due: YYYY-MM-DD)`.
- Tổng kết (block đầu tiên):
  - `Tổng sắp đến hạn: X`
  - `Tổng quá hạn: Y`

## 4. Template message báo cáo (khớp `Reporter.build_report_messages`)
Tin gửi Telegram dùng **`parse_mode="HTML"`**.
- Block 1: hai dòng tổng (như trên).
- Block 2 (một message / assignee hoặc nhóm `Unassigned`):
  - **`Assignee:`** — với assignee đã map:
    - Đọc bản ghi user qua `UsersStore.get_user_record_by_telegram_id`.
    - Hiển thị **`@` + `user_name`** (bỏ `@` trùng nếu có trong file); nếu `user_name` rỗng thì **`@` + `telegram_display_name`**; nếu vẫn rỗng thì **`telegram_id`** số (không thêm `@`).
    - Chuỗi sau `Assignee: ` được **`html.escape`** trước khi gửi.
  - `Unassigned`: `Assignee: Unassigned` (plain).
  - `Quá hạn:` / `Sắp đến hạn:` — mỗi dòng issue:
    - `- <a href=".../browse/KEY">KEY</a>: <escaped summary> (due: YYYY-MM-DD)`

> Trong Block 2: giữa phần `Quá hạn` và phần `Sắp đến hạn` có **1 dòng trống**; giữa các dòng issue (bên trong cùng một phần) **không** dùng dòng trống.

> Trong Block 2: chỉ hiển thị heading `Quá hạn`/`Sắp đến hạn` nếu assignee đó có issue thuộc phần tương ứng.

> Lưu ý: Phase 0 đã yêu cầu “cấu trúc cố định”; vì report là format tổng hợp, bạn cần chốt câu chữ template cụ thể để bot luôn render cùng kiểu.

## 4.1. Chi tiết phân luồng message gửi Telegram
- Gửi `1 message` tổng quan (chứa Block 1).
- Sau đó `1 message` chi tiết cho `mỗi assignee` (chứa Block 2 tương ứng).
- Nếu một nhóm (sắp đến hạn/quá hạn) bằng 0 issue thì tổng tương ứng là `0`; Block 2 chỉ gửi cho assignee (hoặc `Unassigned`) có issue.
- Tất cả message report được gửi vào **1** chat/group (chat đầu tiên) trong `config.telegram.allowed_chat_ids`.

## 4.2. Thứ tự sắp xếp
- Trong mỗi assignee/group (`Unassigned` là một nhóm riêng): sắp xếp issue theo `duedate` tăng dần; nếu trùng `duedate` thì theo `issue key` tăng dần.
- Thứ tự các assignee trong các message Block 2: theo **`telegram_id` số** tăng dần; `Unassigned` đặt cuối (không sort theo chuỗi hiển thị `@username`).

## 5. Acceptance criteria
- Bot chạy báo cáo đúng các mốc trong `due.notification.report_times` (timezone `report_timezone`).
- Report phản ánh đúng `duedate` trong Jira tại thời điểm chạy.
- Không report assignee không có mapping telegram (trừ nhóm `Unassigned`).
- Nếu Jira API lỗi:
  - không làm chết toàn bộ bot
  - log ops đầy đủ (trace id/correlation id nếu có)
  - gửi `1 message` ngắn “hệ thống đang lỗi” tới chat/group đầu tiên trong `config.telegram.allowed_chat_ids`
  - không gửi report của lần chạy đó (để tránh báo cáo thiếu/không nhất quán).

