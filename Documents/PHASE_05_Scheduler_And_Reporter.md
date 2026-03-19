# Phase 5: Scheduler & Reporter (2 lần/ngày)

## 1. Mục tiêu
- Chạy job định kỳ theo cấu hình:
  - Timezone: `Asia/Ho_Chi_Minh`
  - Times: `["08:00", "17:00"]` (cấu hình được)
- Mỗi lần chạy:
  - Query Jira lấy các issue theo `duedate`
  - Tách 2 nhóm:
    - “Sắp đến hạn”: `duedate` trong cửa sổ `[start, end]`
    - “Quá hạn”: `duedate` < `now`
  - Group kết quả theo `assignee.accountId`
  - Filter để chỉ report các assignee có mapping telegram (các thành viên trong nhóm Telegram)
  - Gửi message báo cáo vào group Telegram theo template cố định.

## 2. Query strategy (contract)
### 2.1. “Quá hạn”
- Điều kiện: `duedate` < `now`
- Lưu ý: do `duedate` là ngày, cần chuẩn hóa “now” về timezone config khi so sánh.

### 2.2. “Sắp đến hạn”
- Điều kiện theo window:
  - `duedate` nằm trong khoảng `now`..`now+N ngày` (theo quy ước đã chốt ở Phase 0)

### 2.3. Pagination & rate limit
- Dự trù Jira có thể có nhiều issue:
  - dùng pagination (startAt/maxResults)
  - retry khi gặp rate limit (HTTP 429) theo backoff

## 3. Dữ liệu hiển thị trong report
- Với mỗi assignee:
  - Danh sách issue: `issue key + summary + (optional) due date`
- Tổng kết:
  - tổng sắp đến hạn
  - tổng quá hạn

## 4. Template message báo cáo (thiết kế)
Khuyến nghị dùng 2 block tách rõ (tránh quá dài):
- Block 1: tổng quan
  - “Tổng sắp đến hạn: X”
  - “Tổng quá hạn: Y”
- Block 2: chi tiết theo assignee
  - `Assignee: <telegram_display_or_id>`
  - `- <ISSUEKEY>: <summary> (due: <date>)`

> Lưu ý: Phase 0 đã yêu cầu “cấu trúc cố định”; vì report là format tổng hợp, bạn cần chốt câu chữ template cụ thể để bot luôn render cùng kiểu.

## 5. Acceptance criteria
- Bot chạy được 2 lần/ngày đúng giờ.
- Report phản ánh đúng `duedate` trong Jira tại thời điểm chạy.
- Không report assignee không có mapping telegram.
- Nếu Jira API lỗi:
  - không làm chết toàn bộ bot
  - log ops đầy đủ (trace id)
  - có thể gửi 1 message ngắn “hệ thống đang lỗi” theo policy bạn chốt.

