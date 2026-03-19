# Phase 6: Testing & Hardening (No Code)

## 1. Mục tiêu
- Chứng minh logic conversation và reporter hoạt động đúng các rule/contract đã chốt.
- Giảm rủi ro production: rate limit, race condition, file upload lỗi, template mismatch.

## 2. Unit test targets (không gọi mạng)
- Intent router:
  - `giao việc`, `việc của tôi` map đúng intent.
  - input lạ -> `unknown` và bot trả template giới thiệu lại.
- Validators:
  - DueDays: phải là số nguyên dương; sai -> báo lỗi theo rule.
  - Checklist: parse theo dòng, bỏ dòng rỗng, dừng khi gặp “Không”.
  - Parsing file upload flow: nếu user không upload file thì attachments = [].
- Template renderer:
  - render đúng câu chữ cố định (để tuân thủ yêu cầu “cấu trúc cố định”).

## 3. Integration tests (mock Jira + mock Telegram)
- JiraClient contract:
  - create main issue payload đúng keys/fields contract.
  - create subtasks: parent issue key đúng, checklist items chuyển đúng summary.
  - upload attachments: gửi đúng multipart và header token check.
- Reporter:
  - query phân loại đúng “sắp đến hạn” vs “quá hạn”.
  - group theo assignee và filter theo users.json.

## 4. Hardening list
- Rate limiting:
  - backoff/retry khi Jira trả 429.
- Idempotency cho reporter:
  - tránh gửi trùng nếu job chạy lại (cần cơ chế đánh dấu theo ngày + khung giờ).
- Conversation concurrency:
  - state per chat/user.
  - chống overwriting conversation buffer khi có tin nhắn đến nhanh.
- users.json write safety:
  - lock file + atomic replace như Phase 4.
- Observability:
  - logs cấu trúc: `telegram_chat_id`, `telegram_user_id`, `intent`, `jira_account_id`, `jira_issue_key`.

## 5. Acceptance criteria
- Test pass cho:
  - 2 use case chính (`giao việc`, `việc của tôi`)
  - input sai intent
  - do days validation
  - checklist parsing
  - reporter phân loại theo duedate window

