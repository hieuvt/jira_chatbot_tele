# Phase 2: Jira Client (Cloud REST) (No Telegram)

## 1. Mục tiêu
- Tạo lớp `JiraClient` đủ năng lực để:
  - check membership/admin theo `project_key`
  - tạo main issue
  - tạo sub-tasks từ checklist
  - upload attachment lên issue
  - query issues theo `duedate` cho reporter (để tái sử dụng ở Phase 5)

## 1.1. Giả định nền tảng (đã chốt)
- Auth Jira Cloud: **Basic (email + API token)** bằng **service account**.
- **Không impersonation** / không per-user token.
- Không lưu local role admin để tránh sai lệch; thông tin admin/member phải lấy trực tiếp từ Jira tại thời điểm check.

## 2. Jira Cloud: các payload/fields cần chuẩn hóa
### 2.1. Assignee
- Bot sẽ dùng `jira_account_id` (Jira Cloud “accountId”) làm assignee.

### 2.2. Issue tạo main
Main issue payload (mức contract):
- `project.key` = `config.jira.project_key`
- `issuetype.id` theo `config.jira.issue_type_id`
- `summary` = input từ người dùng
- `description` = input từ người dùng (ADF - Atlassian Document Format)
- `assignee.accountId` = `jira_account_id` assignee
- `duedate` = ngày tính từ “due days”

### 2.3. Sub-task tạo từ checklist
Mỗi checklist item -> 1 sub-task:
- `issuetype.id` = `config.jira.subtask_issue_type_id`
- `parent` = issue key của main task
- `summary` = checklist item text (hoặc map sang field mô tả theo rule)
- Giới hạn Phase 2: tối đa **20** checklist items/subtasks cho mỗi request.

### 2.4. Attachments
- Với file upload từ Telegram, Jira cần:
  - upload endpoint theo issue key
  - multipart/form-data
  - header `X-Atlassian-Token: no-check` (thường dùng cho Jira)

## 2.5. Quy ước/chuẩn hóa thêm (bắt buộc để tránh lỗi 400)
- `duedate` (Jira Cloud) dùng định dạng **date-only**: `YYYY-MM-DD`.
- `description` dùng **ADF** (Atlassian Document Format) tối thiểu:
  - 1 document, type=`doc`, version=1, content là list `paragraph` chứa text.
- `issuetype`: dùng **id-only** (không fallback name).
- Timezone chuẩn để tính `due_days`, overdue/window: **Asia/Ho_Chi_Minh**.

## 3. Membership/admin check (contract implement)
### 3.1. `check_project_membership(jira_account_id, project_key) -> bool`
- Mục tiêu: xác định user có thuộc tập người dùng project theo dữ liệu Jira runtime.
- Cách làm (mô tả mức thiết kế):
  - (a) Jira permission (service account): đảm bảo bot có thể browse/create trong `project_key`
  - (b) Truy vấn Jira project roles/actors để xác định `jira_account_id` có thuộc project hay không
- Định nghĩa member (đã chốt): user xuất hiện trong **bất kỳ role actors** nào của project thì được coi là member.

### 3.2. `check_project_admin(jira_account_id, project_key) -> bool`
- Mục tiêu: quyết định “user có quyền assign cho người khác” theo role admin thực tế từ Jira.
- Cách làm:
  - (a) Jira permission (service account): đảm bảo bot có quyền cần thiết để set assignee trên issue
  - (b) Truy vấn Jira project roles để xác định `jira_account_id` thuộc role admin của `project_key`
  - (c) Scope admin: **per-project**
- Quy tắc match admin role (đã chốt): role name **chứa `admin`** (case-insensitive).

### 3.3. Endpoint gợi ý (Jira Cloud REST)
- Permission check (project-scoped): `GET /rest/api/3/mypermissions?projectKey={projectKey}`
  - Kiểm tra tối thiểu cho membership: `BROWSE_PROJECTS` (và/hoặc `CREATE_ISSUES` tùy policy).
  - Kiểm tra admin: `ADMINISTER_PROJECTS`.
- Role lookup để xác định user:
  - `GET /rest/api/3/project/{projectIdOrKey}/role`
  - `GET /rest/api/3/project/{projectIdOrKey}/role/{id}` -> đọc danh sách actors (bao gồm user accountId)
- Lưu ý: `mypermissions` trả permission của **service account**; phần “user là admin/member” lấy từ role actors runtime của Jira.

### 3.4. Rule assign theo quyền
- Admin (theo Jira role của project): được assign cho người khác.
- Non-admin: chỉ được assign cho chính mình.

## 4. Query issues cho reporter (contract implement)
### 4.1. Các tiêu chí phân loại (trong `Reporter` sau khi query)
- `now` và `today` theo timezone báo cáo (`due.notification.report_timezone`, mặc định `Asia/Ho_Chi_Minh`).
- “Quá hạn”: `duedate` (date-only) **&lt; `today`**.
- “Sắp đến hạn”: `today` ≤ `duedate` ≤ `today + window_days` (**inclusive**).

### 4.2. Group theo assignee
- Với mỗi issue: lấy `assignee.accountId` (hoặc nhóm `unassigned` nếu không có assignee).
- `Reporter` map Jira assignee → Telegram qua `users.json` (`get_reverse_mapping`); không lọc theo reporter.

### 4.3. JQL + pagination (triển khai hiện tại trong `JiraClient.query_issues_by_due_date_for_reporter`)
- **Không** lọc theo `reporter` — báo cáo theo toàn bộ issue có `duedate` trong project (đúng product spec Phase 5).
- JQL tối thiểu:
  - `project = "{projectKey}" AND duedate IS NOT EMPTY AND duedate <= "{today+window_days as YYYY-MM-DD}"`
- Client gọi API search với JQL trên, rồi **lọc thêm trong Python** (`_in_due_window`) để tách đúng overdue vs upcoming.
- Pagination: `startAt` / `maxResults` / `total`; giới hạn `max_pages` (config `jira.search.max_pages`, mặc định 20).
- Fields: `summary,assignee,duedate,status,project,issuetype`

## 5. Config bắt buộc (không hardcode)
- `config.jira.base_url` (ví dụ `https://<tenant>.atlassian.net`)
- `config.jira.auth`:
  - Basic: `email` + `api_token`
- `config.jira.project_key`
- `config.jira.issue_type_id`
- `config.jira.subtask_issue_type_id`
- `config.jira.timezone` = `Asia/Ho_Chi_Minh`
- `config.jira.search.max_results` = `50` (mặc định)
- `config.jira.search.max_pages` = `20` (mặc định)
- `config.jira.http.retry` (429/5xx backoff) + `config.jira.http.timeout_seconds`
- `config.jira.attachments.max_size_mb` (nếu cần policy giới hạn)

## 6. Error handling plan
Các nhóm lỗi nên có mapping để bot phản hồi đúng template:
- 401/403: auth/permission -> bot nói “bạn không phải…” hoặc cần kiểm tra credential (không lộ token)
- 404: project/issue type không tồn tại -> log ops + fail gracefully
- 400: field format lỗi (duedate không đúng định dạng, description quá dài, …)
- File upload lỗi: **fail toàn bộ** (không coi create main issue là thành công nếu attachment upload fail)
- Khi nhiều file: thử upload tất cả; nếu có bất kỳ lỗi, trả fail-all.
- Subtask tạo lỗi giữa chừng: fail nghiệp vụ và trả danh sách subtask đã tạo (để xử lý bù/quan sát).

### 6.1. Rate limit / retry (tối thiểu)
- 429: retry với exponential backoff + jitter (tôn trọng `Retry-After` nếu có).
- 5xx / timeout: retry số lần hữu hạn.
- 4xx (trừ 429): không retry, trả lỗi map theo template.

### 6.2. Error contract (typed)
- Chuẩn lỗi trả về từ `JiraClient`: `{ code, message, context, retriable }`.
- `code`: mã domain-level ổn định để bot map template.
- `context`: thông tin có kiểm soát (issueKey/projectKey/status), không lộ credential/token/raw secret.
- `retriable`: `true` cho lỗi có thể retry (429/5xx/timeout theo policy), ngược lại `false`.

## 7. Acceptance criteria
- Có tài liệu mô tả request/response contract cho:
  - create main issue
  - create subtasks
  - upload attachments
  - query issues by duedate
- Có danh sách trường “cần config” không được hardcode.
- Có kế hoạch rate limit & pagination khi query nhiều issues (đảm bảo reporter chạy ổn định).

