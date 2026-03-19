# Phase 3: Telegram Bot State Machine (python-telegram-bot) (No Jira deep logic)

## 1. Mục tiêu
- Implement (ở mức thiết kế) flow conversation cho 2 intent:
  - `giao việc`
  - `việc của tôi`
- Xử lý file upload và checklist nhập vào conversation buffer.
- Đảm bảo:
  - các intent xử lý nội bộ (không dùng LLM)
  - sai intent -> bot trả đúng template “giới thiệu lại nhập đúng”
  - mỗi prompt dùng đúng câu chữ template cố định

## 2. Conversation flow (thiết kế states)
### 2.1. `giao việc` (tóm tắt theo user mermaid)
- Verify sender có mapping trong `users.json`:
  - nếu thiếu -> hỏi `jira_account_id` của người gửi
  - sau đó check membership project
- Verify sender có quyền Admin:
  - nếu không -> trả: `Chỉ Admin của project mới có quyền giao việc`
- Chọn assignee:
  - Admin chọn người khác
  - Member không được chọn assignee khác
- Verify assignee trong `users.json` (hoặc hỏi `jira_account_id`):
  - nếu assignee chưa có mapping -> hỏi đúng template
- Verify assignee là member project:
  - nếu không -> trả: `assignee không phải thành viên của project. Hãy kiểm tra jira trước`
- Collect:
  - Summary
  - Description
  - (File optional) theo template: `Bạn có muốn thêm file...`
  - (Checklist optional) theo template: `Bạn có muốn thêm việc trong checklist...`
  - Due days (bắt buộc số)
- Tạo main issue + subtasks + attachments (thực hiện qua JiraClient ở Phase 2)

### 2.2. `việc của tôi`
- Giống `giao việc` nhưng:
  - không cần step “Admin/assignee khác”
  - assignee = người gửi hiện tại

## 3. Router & intent handling
### 3.1. Router
- Input: message text + telegram sender id.
- Output:
  - intent enum + payload (nếu có)
  - nếu unknown -> intent = `unknown`

### 3.2. Rule sai intent
- Khi `unknown`:
  - bot trả template cố định để người dùng nhập đúng intent.
- Quy định cụ thể (Phase 0 cần chốt text đầy đủ).

## 4. Data captured trong conversation buffer
- `sender_telegram_id`
- `sender_jira_account_id` (có thể null đến khi user cung cấp)
- `assignee_jira_account_id`
- `summary`
- `description`
- `checklist_items` (list[str] hoặc [])
- `due_days` (int > 0)
- `attachments` (list[file_meta]) hoặc []:
  - file_meta gồm: filename, size, telegram file id (mô tả)

## 5. File upload rule
- Ở câu hỏi: `Bạn có muốn thêm file... Nếu muốn thì upload file. Nếu không thì nói Không`
- Quy ước:
  - Nếu user gửi “Không” ngay: bỏ qua attachments.
  - Nếu user gửi file:
    - bot tải file từ Telegram server
    - lưu vào buffer để Phase 2 upload sang Jira

## 6. Due days validation
- Prompt: `Nhập số ngày cần hoàn thành. Yêu cầu nhập giá trị số`
- Rules:
  - DueDays phải là số nguyên dương
  - Nếu sai định dạng:
    - bot nhắc lại prompt (template cố định) hoặc message validation (cần quy ước trong Phase 0)

## 7. Checklist parsing rule
- Prompt “Nếu muốn hãy viết luôn công việc...”
- Quy ước:
  - Checklist được nhập theo dòng (mỗi dòng 1 item) cho đến khi user nói `Không` hoặc gửi một delimiter (cần chốt).
  - Những dòng rỗng hoặc khoảng trắng bị bỏ qua.

## 8. Integration points
- Bot gọi JiraClient theo các contract:
  - `check_project_membership`
  - `check_project_admin`
  - `create_issue`
  - `create_subtasks`
  - `upload_attachments`
- Bot cập nhật users.json qua `UsersStore`:
  - upsert mapping khi thiếu `jira_account_id`

## 9. Acceptance criteria
- Đảm bảo flow đúng theo use case diagram.
- Mọi prompt chính đều dùng đúng template cố định đã chốt ở Phase 0.
- Bot không dùng LLM để hiểu intent; chỉ parse text theo rule.

