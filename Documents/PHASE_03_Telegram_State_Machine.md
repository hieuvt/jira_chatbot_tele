# Phase 3: Telegram Bot State Machine (python-telegram-bot) (No Jira deep logic)

## 1. Mục tiêu
- Thiết kế state machine hội thoại cho 2 intent:
  - `giao việc`
  - `việc của tôi`
- Thu thập đủ dữ liệu để gọi `JiraClient` (Phase 2), không chứa nghiệp vụ Jira sâu trong bot.
- Đảm bảo:
  - parse intent theo rule (không dùng LLM)
  - prompt/validation dùng template cố định
  - có quy tắc rõ cho `unknown`, `huy`, timeout, input sai định dạng

## 2. Từ vựng và quy ước dùng chung
- Từ khóa hệ thống:
  - `KHONG` = một trong: `không`, `khong`, `no` (không phân biệt hoa thường, trim khoảng trắng)
  - `HUY` = một trong: `hủy`, `huy`, `/cancel`
  - `XONG` = một trong: `xong`, `done`, `/done`
  - `CO` = một trong: `có`, `co`, `yes` (không phân biệt hoa thường, trim khoảng trắng)
- Bất kỳ state nào nếu nhận `HUY`:
  - kết thúc conversation hiện tại
  - clear conversation buffer
  - trả template: `Đã hủy thao tác hiện tại. Bạn có thể nhập lại: "giao việc" hoặc "việc của tôi".`
- Group/supergroup:
  - Bot cho phép nhiều người thao tác song song trong cùng 1 group.
  - Conversation buffer key = `(chat_id, user_id)` (mỗi người 1 phiên trong cùng group).
  - Khi bot hỏi `jira_account_id` (sender/assignee), user nhập trực tiếp trong group (public).
- Project scope:
  - `project_key` dùng 1 giá trị global từ `config.jira.project_key` cho mọi chat/user.
- Timeout phiên hội thoại:
  - nếu không có tương tác trong `conversation.timeout_minutes` (mặc định 10 phút) thì auto end và clear buffer
  - tin nhắn sau timeout sẽ được xem như phiên mới
- Input type theo state:
  - `S8_ASK_ATTACHMENTS`: nhận text điều khiển (`KHONG`, `XONG`) và mọi media/file.
  - Các state còn lại chỉ nhận input text; nếu nhận media/file/sticker thì bot nhắc lại prompt của state hiện tại.

## 3. Router & intent handling
### 3.1. Router input/output
- Input: `chat_id`, `user_id` (telegram sender id), `message_text`, metadata (có file hay không).
- Output:
  - `intent` thuộc enum: `ASSIGN_TASK`, `MY_TASK`, `UNKNOWN`
  - `payload` (nếu parse được tham số)
- Nếu đang có conversation active (theo key `(chat_id, user_id)`):
  - Nếu message text match intent `giao việc` hoặc `việc của tôi`: hủy phiên hiện tại và bắt đầu flow mới theo intent mới.
  - Nếu không match intent: message đi theo state hiện tại.

### 3.2. Rule parse intent
- `giao việc`:
  - match các câu bắt đầu bằng `giao việc` (ví dụ: `giao việc`, `giao việc cho A`)
- `việc của tôi`:
  - match các câu bắt đầu bằng `việc của tôi`
- Còn lại: `UNKNOWN`

### 3.3. Rule với `UNKNOWN`
- Bot trả đúng template cố định:
  - `Mình chưa hiểu yêu cầu. Bạn hãy nhập đúng 1 trong 2 lệnh: "giao việc" hoặc "việc của tôi".`
- Không tạo conversation buffer mới khi `UNKNOWN`.

## 4. State machine chi tiết
## 4.1. Luồng `giao việc`
1) `S0_START_ASSIGN`
- Kiểm tra mapping sender trong `users.json`.
- Nếu thiếu `sender_jira_account_id` -> sang `S1_ASK_SENDER_JIRA_ID`.
- Nếu có -> sang `S2_CHECK_SENDER_MEMBER`.

2) `S1_ASK_SENDER_JIRA_ID`
- Prompt: `Bạn chưa liên kết Jira. Vui lòng nhập jira_account_id của bạn.`
- Input hợp lệ: chuỗi không rỗng.
- On success:
  - upsert mapping qua `UsersStore`
  - set `sender_jira_account_id`
  - sang `S2_CHECK_SENDER_MEMBER`

3) `S2_CHECK_SENDER_MEMBER`
- Gọi `check_project_membership(sender_jira_account_id, project_key)`.
- Nếu false -> end với template:
  - `Bạn chưa là thành viên của project trên Jira. Vui lòng kiểm tra lại quyền trước khi dùng bot.`
- Nếu true -> sang `S3_CHECK_SENDER_ADMIN`.

4) `S3_CHECK_SENDER_ADMIN`
- Gọi `check_project_admin(sender_jira_account_id, project_key)`.
- Nếu false -> end với template:
  - `Chỉ Admin của project mới có quyền giao việc.`
- Nếu true -> sang `S4_ASK_ASSIGNEE`.

5) `S4_ASK_ASSIGNEE`
- Prompt: `Chọn người được giao việc: reply tin nhắn của họ hoặc @mention họ. Nếu không, bạn có thể nhập trực tiếp jira_account_id.`
- Input hợp lệ (một trong):
  - reply một message của user cần giao việc -> lấy `replied_user_id`
  - message có @mention user -> lấy `mentioned_user_id`
  - nhập trực tiếp `jira_account_id` (chuỗi không rỗng)
- Rule:
  - Nếu nhận `replied_user_id` hoặc `mentioned_user_id`:
    - lookup `users.json` theo `telegram_user_id` để lấy `assignee_jira_account_id`
    - nếu không có mapping -> hỏi `jira_account_id` của assignee (dùng `TPL_ASK_ASSIGNEE`) và upsert vào `UsersStore`
  - Nếu nhập trực tiếp `jira_account_id`: set `assignee_jira_account_id`
- Sang `S5_CHECK_ASSIGNEE_MEMBER`.

6) `S5_CHECK_ASSIGNEE_MEMBER`
- Gọi `check_project_membership(assignee_jira_account_id, project_key)`.
- Nếu false -> end với template:
  - `Người được giao không phải thành viên của project. Hãy kiểm tra Jira trước khi giao việc.`
- Nếu true -> sang `S6_ASK_SUMMARY`.

7) `S6_ASK_SUMMARY`
- Prompt: `Nhập tiêu đề công việc (summary).`
- Validation:
  - không rỗng, sau trim phải có ký tự
  - max length khuyến nghị: 255
- Sang `S7_ASK_DESCRIPTION`.

8) `S7_ASK_DESCRIPTION`
- Prompt: `Nhập mô tả công việc (description).`
- Validation: không rỗng sau trim.
- Sang `S8_ASK_ATTACHMENTS`.

9) `S8_ASK_ATTACHMENTS`
- Prompt: `Bạn có muốn thêm file đính kèm không? Nếu có hãy upload file. Nếu không, nhập "Không". Khi upload xong, nhập "Xong".`
- Rule:
  - chấp nhận mọi loại Telegram attachment/media (document/photo/video/audio/voice/...)
  - tải file ngay khi user gửi, lưu dữ liệu vào RAM cho phiên hiện tại
  - nhận nhiều file liên tiếp
  - `KHONG` ngay bước đầu -> bỏ qua file, sang `S9_ASK_CHECKLIST`
  - sau khi có >=1 file, user nhập `XONG` -> sang `S9_ASK_CHECKLIST`
  - nếu user nhập text khác `KHONG/XONG` và không có file -> nhắc lại prompt
- Giới hạn:
  - max files theo `config.telegram.attachments.max_files` (mặc định 10)
  - max size từng file theo `config.jira.attachments.max_size_mb` (nếu cấu hình)
  - tổng dung lượng attachments trong RAM cho 1 phiên: tối đa 20MB
  - nếu vượt 20MB: từ chối file mới và nhắc user gửi file nhỏ hơn hoặc bỏ bớt file
  - khi phiên kết thúc (`HUY`, timeout, restart intent, tạo Jira thành công hoặc thất bại): xóa ngay toàn bộ dữ liệu file trong RAM

10) `S9_ASK_CHECKLIST`
- Prompt: `Bạn có muốn thêm checklist không? Nếu có, nhập mỗi dòng một việc. Nhập "Không" để bỏ qua, hoặc "Xong" để kết thúc checklist.`
- Rule:
  - `KHONG` ngay bước đầu -> `checklist_items = []`, sang `S10_ASK_DUE_DAYS`
  - mỗi message text (khác `XONG`) được tách theo dòng, trim, bỏ dòng rỗng, append vào checklist
  - `XONG` -> kết thúc checklist
- Giới hạn: tối đa 20 items (khớp giới hạn Phase 2 `create_subtasks`)

11) `S10_ASK_DUE_DAYS`
- Prompt: `Nhập số ngày cần hoàn thành (số nguyên dương).`
- Validation:
  - phải parse được int
  - `due_days > 0`
- Sai định dạng -> trả template validation và ở lại state này:
  - `Giá trị không hợp lệ. Vui lòng nhập số nguyên dương cho số ngày hoàn thành.`
- Hợp lệ -> sang `S11_CONFIRM`.

12) `S11_CONFIRM`
- Bot trả bản tóm tắt dữ liệu đã nhập và hỏi xác nhận tạo Jira:
  - assignee
  - summary
  - description (rút gọn tối đa 500 ký tự, quá thì thêm `...`)
  - số checklist items
  - số attachments
  - due_days
- Input hợp lệ:
  - `CO` -> sang `S12_CREATE`
  - `KHONG` -> end phiên và clear buffer
- Input khác `CO/KHONG` -> trả template nhắc nhập lại xác nhận và ở lại state này.

13) `S12_CREATE`
- Bot gọi tuần tự:
  - `create_issue`
  - `create_subtasks` (nếu checklist không rỗng)
  - `upload_attachments` (nếu có file)
- Quy tắc fail:
  - bất kỳ bước nào lỗi -> trả lỗi theo mapping `JiraClientError.code`, end phiên
  - riêng attachment lỗi: coi là fail toàn bộ theo quy ước Phase 2
- Thành công -> trả kết quả có `issue_key`, số subtask, số file upload, rồi clear buffer và end.

## 4.2. Luồng `việc của tôi`
- Dùng chung states thu thập dữ liệu từ `S0` đến `S12`, khác ở phần assignee:
  - bỏ `S3_CHECK_SENDER_ADMIN`, `S4_ASK_ASSIGNEE`, `S5_CHECK_ASSIGNEE_MEMBER`
  - `assignee_jira_account_id = sender_jira_account_id`
- Luồng tối thiểu:
  - `S0 -> S1? -> S2 -> S6 -> S7 -> S8 -> S9 -> S10 -> S11 -> S12`

## 5. Dữ liệu conversation buffer
- `intent`
- `chat_id`
- `user_id` (telegram sender id)
- `sender_jira_account_id` (nullable trước khi user nhập)
- `assignee_jira_account_id`
- `summary`
- `description`
- `checklist_items: list[str]` (mặc định `[]`)
- `due_days: int` (`> 0`)
- `attachments: list[file_meta]` (mặc định `[]`)
- `state`
- `started_at`, `updated_at`

`file_meta` tối thiểu gồm:
- `filename`
- `size`
- `telegram_file_id`
- `telegram_file_unique_id` (nếu Telegram cung cấp)
- `kind` (ví dụ: `document`, `photo`, `video`, `audio`, `voice`, ...)
- `mime_type` (nếu Telegram cung cấp)
- `content_bytes` (lưu trong RAM trong thời gian phiên còn hiệu lực)

Quy ước tên file cho media không có filename:
- Dùng pattern: `<kind>_<timestamp>.<ext>`
- `ext` suy ra từ MIME type nếu có; nếu không suy ra được thì dùng `.bin`

## 6. Mapping lỗi từ JiraClient sang bot message
- Input lỗi từ `JiraClientError`: `{code, message, context, retriable}`.
- Mapping tối thiểu cần có:
  - `JIRA_AUTH_OR_PERMISSION` -> `Bot chưa đủ quyền thao tác trên Jira. Vui lòng liên hệ quản trị viên.`
  - `JIRA_BAD_REQUEST` / `JIRA_INVALID_DUE_DATE` -> `Dữ liệu chưa hợp lệ để tạo việc. Vui lòng kiểm tra lại thông tin đã nhập.`
  - `JIRA_RATE_LIMITED` + `retriable=true` -> `Jira đang giới hạn tần suất. Vui lòng thử lại sau ít phút.`
  - `JIRA_NOT_FOUND` -> `Cấu hình Jira chưa đúng hoặc tài nguyên không tồn tại. Vui lòng báo quản trị viên kiểm tra project/issue type.`
  - `JIRA_SERVER_ERROR` / `JIRA_HTTP_ERROR` / `JIRA_INVALID_JSON` / `JIRA_UNKNOWN_ERROR` -> `Đã có lỗi khi tạo công việc trên Jira. Vui lòng thử lại sau.`
  - fallback -> `Đã có lỗi khi tạo công việc trên Jira. Vui lòng thử lại sau.`

## 7. Template prompts chuẩn hóa (áp dụng cố định)
- `TPL_UNKNOWN_INTENT`:
  - `Mình chưa hiểu yêu cầu. Bạn hãy nhập đúng 1 trong 2 lệnh: "giao việc" hoặc "việc của tôi".`
- `TPL_ASK_SENDER_JIRA_ID`:
  - `Bạn chưa liên kết Jira. Vui lòng nhập jira_account_id của bạn.`
- `TPL_NOT_PROJECT_MEMBER`:
  - `Bạn chưa là thành viên của project trên Jira. Vui lòng kiểm tra lại quyền trước khi dùng bot.`
- `TPL_NOT_ADMIN_ASSIGN`:
  - `Chỉ Admin của project mới có quyền giao việc.`
- `TPL_ASK_ASSIGNEE`:
  - `Người này chưa liên kết Jira. Vui lòng nhập jira_account_id của người được giao việc.`
- `TPL_ASSIGNEE_NOT_MEMBER`:
  - `Người được giao không phải thành viên của project. Hãy kiểm tra Jira trước khi giao việc.`
- `TPL_ASK_SUMMARY`:
  - `Nhập tiêu đề công việc (summary).`
- `TPL_ASK_DESCRIPTION`:
  - `Nhập mô tả công việc (description).`
- `TPL_ASK_ATTACHMENTS`:
  - `Bạn có muốn thêm file đính kèm không? Nếu có hãy upload file. Nếu không, nhập "Không". Khi upload xong, nhập "Xong".`
- `TPL_ASK_CHECKLIST`:
  - `Bạn có muốn thêm checklist không? Nếu có, nhập mỗi dòng một việc. Nhập "Không" để bỏ qua, hoặc "Xong" để kết thúc checklist.`
- `TPL_ASK_DUE_DAYS`:
  - `Nhập số ngày cần hoàn thành (số nguyên dương).`
- `TPL_INVALID_DUE_DAYS`:
  - `Giá trị không hợp lệ. Vui lòng nhập số nguyên dương cho số ngày hoàn thành.`
- `TPL_CONFIRM_CREATE`:
  - `Xác nhận tạo công việc với thông tin trên? Nhập "Có" để tạo, hoặc "Không" để hủy.`
- `TPL_INVALID_CONFIRM`:
  - `Giá trị không hợp lệ. Vui lòng nhập "Có" hoặc "Không".`
- `TPL_CANCELLED`:
  - `Đã hủy thao tác hiện tại. Bạn có thể nhập lại: "giao việc" hoặc "việc của tôi".`

## 8. Integration points
- Gọi `JiraClient` (Phase 2):
  - `check_project_membership`
  - `check_project_admin`
  - `create_issue`
  - `create_subtasks`
  - `upload_attachments`
- Gọi `UsersStore`:
  - lấy mapping `telegram_id -> jira_account_id`
  - upsert mapping khi user vừa nhập `jira_account_id`
- Không gọi LLM trong router hoặc state transitions.

## 9. Acceptance criteria
- Có state machine đủ chi tiết để implement trực tiếp bằng `ConversationHandler`.
- Mỗi state có:
  - prompt cố định
  - điều kiện input hợp lệ
  - rule chuyển state
  - rule lỗi/nhắc lại
- Luồng `giao việc` và `việc của tôi` tuân thủ đúng quyền theo contract Phase 2.
- Không còn placeholder kiểu “cần chốt” cho các điểm vận hành chính (unknown/cancel/checklist delimiter/file done/validation).
- Mapping lỗi bot dùng đúng `JiraClientError.code` hiện có trong Phase 2 (`JIRA_*`).
- Rule file RAM rõ ràng: tải ngay, giới hạn tổng 20MB/phiên, và cleanup ngay khi kết thúc phiên.

