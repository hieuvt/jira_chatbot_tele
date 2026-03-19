# Phase 0: Requirements & Conversation Design (No Code)

## 0. Mục tiêu phase
- Chốt “contract” dữ liệu và quy ước để các phase sau implement ổn định.
- Chuẩn hóa các template câu trả lời cố định theo từng bước.
- Xác định rõ các rule permission, deadline, checklist/sub-tasks.

## 1. Inputs/Outputs
### Inputs
- `users.json`: mapping `telegram_account_id` <-> `jira_account_id`.
- Thông tin Jira Cloud:
  - `jira.base_url`
  - `jira.email`
  - `jira.api_token`
  - `jira.project_key`
  - `jira.issue_type_key` (issue type của main task; mặc định “TASK” theo thỏa thuận)
  - `jira.subtask_issue_type_key`
  - Chuẩn “assignee field” lấy `accountId` của Jira.
- Thông tin Telegram:
  - `allowed_chat_ids` (chỉ chạy trong group mong muốn).

### Outputs (deliverable của phase)
- File `CONFIG` (ví dụ JSON/YAML) gồm đầy đủ tham số chạy bot và scheduler.
- Chuẩn format `users.json`.
- Danh sách intent + rule routing.
- Template câu trả lời cố định (text) cho từng bước.
- Danh sách state của conversation cho `giao việc` và `việc của tôi`.

## 2. Chuẩn hóa `users.json`
Đề xuất format:
```json
{
  "telegram_account_id_1": "jira_account_id_1",
  "telegram_account_id_2": "jira_account_id_2"
}
```

Quy tắc validate:
- Key và value đều là chuỗi.
- Nếu `telegram_account_id` có nhưng value rỗng/không hợp lệ -> coi như chưa có mapping.
- Không overwrite mapping khi đã tồn tại (hiện tại).

## 3. Chuẩn hóa `config`
Các trường tối thiểu:
```json
{
  "telegram": {
    "allowed_chat_ids": [123, 456]
  },
  "jira": {
    "base_url": "https://your-domain.atlassian.net",
    "email": "user@company.com",
    "api_token": "JIRA_API_TOKEN",
    "project_key": "ABC",
    "issue_type_key": "TASK",
    "subtask_issue_type_key": "SUBTASK",
    "admin_project_role_name": "Administrator",
    "attachment_max_bytes": 10485760
  },
  "due": {
    "notification": {
      "window_days": 3,
      "report_timezone": "Asia/Ho_Chi_Minh",
      "report_times": ["08:00", "17:00"]
    }
  }
}
```

## 4. Permission & membership rules (Jira)
### 4.1. Thành viên dự án
- Khi bot cần “verify user is member of project”:
  - Query Jira để kiểm tra quyền/permission của `jira_account_id` trên `project_key`.
  - Nếu không có quyền tương đương thành viên: bot trả về message đúng template:
    - `bạn không phải là thành viên của project, hãy liên hệ với Admin`

### 4.2. Admin của dự án (chỉ cho `giao việc`)
- Khi user nói `giao việc` và muốn giao cho người khác:
  - Bot kiểm tra user có thuộc Jira project role có tên `config.jira.admin_project_role_name` hay không.
  - Nếu không: bot trả về:
    - `Chỉ Admin của project mới có quyền giao việc`

## 5. Due date interpretation
- “Sắp đến hạn” theo `window_days = N` (khuyến nghị mặc định):
  - bao gồm `today` (từ đầu hôm nay đến hết ngày `today + N`)
  - so sánh theo timezone báo cáo `Asia/Ho_Chi_Minh`
- “Quá hạn”:
  - `duedate` < thời điểm chạy báo cáo

## 6. Parsing checklist -> Sub-tasks
Rule đề xuất:
- Bot hỏi người dùng viết checklist item.
- Mỗi dòng là 1 item (bot không hỗ trợ tách nhiều item trên 1 dòng bằng dấu phân tách).
- Khi user nhập `Không`:
  - không tạo sub-tasks.
- Checklist text sẽ được dùng làm `summary` hoặc field mô tả sub-task (tùy Jira fields; mặc định summary).

## 7. Template câu trả lời cố định (theo use case)
### 7.1. Khi người dùng chưa có `jira_account_id` trong `users.json`
- `không có thông tin jira account id trong cơ sở dữ liệu. Hãy gửi cho tôi jira account id của bạn `

### 7.2. Khi người dùng không phải member project
- `bạn không phải là thành viên của project, hãy liên hệ với Admin`

### 7.3. Khi user không phải Admin mà muốn `giao việc` cho người khác
- `Chỉ Admin của project mới có quyền giao việc`

### 7.4. Khi chưa có mapping cho assignee
- `không có thông tin về assignee trong cơ sở dữ liệu. Hãy gửi cho tôi jira account id của assignee`

### 7.5. Khi assignee không phải member project
- `assignee không phải thành viên của project. Hãy kiểm tra jira trước`

### 7.6. Steps tạo task (đều dùng chung cho 2 use case)
- `Nhập Summary công việc`
- `Nhập Description công việc`
- `Bạn có muốn thêm file không. Nếu muốn thì upload file. Nếu không thì nói Không`
- Nếu không file:
  - `Bạn có muốn thêm việc trong checklist không. Nếu muốn hãy viết luôn công việc. Nếu không thì nói Không`
- `Nhập số ngày cần hoàn thành. Yêu cầu nhập giá trị số`

> Lưu ý: các prompt “điền khoảng trống” (Summary/Description/DueDays/Checklist) phải dùng đúng câu chữ trong template để tuân thủ requirement “cấu trúc cố định”.

## 8. State machine (thiết kế)
### 8.1. States đề xuất cho `giao việc`
- `IDLE`
- `VERIFY_SENDER_IN_USERS_DB`
- `ASK_SENDER_JIRA_ID`
- `VERIFY_SENDER_ADMIN`
- `ASK_ASSIGNEE`
- `VERIFY_ASSIGNEE_IN_USERS_DB`
- `ASK_ASSIGNEE_JIRA_ID`
- `VERIFY_ASSIGNEE_MEMBER_PROJECT`
- `ASK_SUMMARY`
- `ASK_DESCRIPTION`
- `ASK_ADD_FILE`
- `ASK_ADD_CHECKLIST`
- `ASK_DUE_DAYS`
- `CREATE_JIRA_TASK`

### 8.2. States đề xuất cho `việc của tôi`
- Các state giống `giao việc` nhưng bỏ qua `VERIFY_SENDER_ADMIN` và `ASK_ASSIGNEE` (assignee = sender).

## 9. Acceptance criteria của phase 0
- `users.json` format được chốt.
- Template câu trả lời được chốt (đúng text theo yêu cầu).
- Permission rule rõ ràng (Admin vs Member).
- Checklist->Subtask rule rõ ràng.
- “Sắp đến hạn” bao gồm hôm nay (today) theo `window_days`.

