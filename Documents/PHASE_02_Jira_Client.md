# Phase 2: Jira Client (Cloud REST) (No Telegram)

## 1. Mục tiêu
- Tạo lớp `JiraClient` đủ năng lực để:
  - check membership/admin theo `project_key`
  - tạo main issue
  - tạo sub-tasks từ checklist
  - upload attachment lên issue
  - query issues theo `duedate` cho reporter (để tái sử dụng ở Phase 5)

## 2. Jira Cloud: các payload/fields cần chuẩn hóa
### 2.1. Assignee
- Bot sẽ dùng `jira_account_id` (Jira Cloud “accountId”) làm assignee.

### 2.2. Issue tạo main
Main issue payload (mức contract):
- `project.key` = `config.jira.project_key`
- `issuetype.name hoặc id` theo `config.jira.issue_type_key`
- `summary` = input từ người dùng
- `description` = input từ người dùng
- `assignee.accountId` = `jira_account_id` assignee
- `duedate` = ngày tính từ “due days”

### 2.3. Sub-task tạo từ checklist
Mỗi checklist item -> 1 sub-task:
- `issuetype` = `config.jira.subtask_issue_type_key`
- `parent` = issue key của main task
- `summary` = checklist item text (hoặc map sang field mô tả theo rule)

### 2.4. Attachments
- Với file upload từ Telegram, Jira cần:
  - upload endpoint theo issue key
  - multipart/form-data
  - header `X-Atlassian-Token: no-check` (thường dùng cho Jira)

## 3. Membership/admin check (contract implement)
### 3.1. `check_project_membership(jira_account_id, project_key) -> bool`
- Mục tiêu: xác định người dùng có quyền tương đương “member của project” hay không.
- Cách làm (mô tả mức thiết kế):
  - dùng endpoint permission liên quan “my permissions”
  - lọc permission có liên quan browse/view project trên `project_key`
- Nếu không thể suy ra membership:
  - fallback: test bằng quyền “create/read in project” (tùy policy bạn chốt)

### 3.2. `check_project_admin(jira_account_id, project_key) -> bool`
- Mục tiêu: xác định “Chỉ Admin mới được giao cho người khác”.
- Triển khai theo permission:
  - tìm permission “ADMINISTER_PROJECTS” hoặc role tương đương trên project

## 4. Query issues cho reporter (contract implement)
### 4.1. Các tiêu chí phân loại
- “Quá hạn”: `duedate` < `now`
- “Sắp đến hạn”: `duedate` trong [start, end] theo `window_days`

### 4.2. Group theo assignee
- Với mỗi issue:
  - lấy `assignee.accountId`
  - map sang `users.json` để biết telegram user tương ứng

## 5. Error handling plan
Các nhóm lỗi nên có mapping để bot phản hồi đúng template:
- 401/403: auth/permission -> bot nói “bạn không phải…” hoặc cần kiểm tra credential (không lộ token)
- 404: project/issue type không tồn tại -> log ops + fail gracefully
- 400: field format lỗi (duedate không đúng định dạng, description quá dài, …)
- File upload lỗi: bot có thể vẫn tạo issue chính (tùy rule), hoặc fail toàn bộ (cần chốt)

## 6. Acceptance criteria
- Có tài liệu mô tả request/response contract cho:
  - create main issue
  - create subtasks
  - upload attachments
  - query issues by duedate
- Có danh sách trường “cần config” không được hardcode.
- Có kế hoạch rate limit & pagination khi query nhiều issues (đảm bảo reporter chạy ổn định).

