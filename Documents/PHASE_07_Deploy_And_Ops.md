# Phase 7: Deploy & Ops (Vận hành)

## 1. Mục tiêu
- Đóng gói để chạy ổn định trong môi trường thực tế.
- Bảo vệ secrets (Jira token, Telegram bot token).
- Đảm bảo logs và rollback dễ dàng.

## 2. Configuration & secrets
Khuyến nghị:
- `config/config.example.json` chứa schema (không có secrets).
- Secrets lấy qua environment variables:
  - `TELEGRAM_BOT_TOKEN`
  - `JIRA_API_TOKEN`
  - (có thể) `JIRA_EMAIL`
  - `TELEGRAM_ALLOWED_CHAT_IDS` nếu muốn gộp vào env

## 3. Running modes
### 3.1 Local (dev)
- Cài dependencies theo `requirements.txt`/`pyproject.toml` (tạo ở Phase implement).
- Chạy entrypoint bot + scheduler trong cùng process.

### 3.2 Production
- Khuyến nghị Docker:
  - Image chạy Python runtime
  - Mount volume chứa `data/users.json` để không mất mapping
  - Mount/copy config read-only

## 4. Logging & monitoring
- Logging tối thiểu:
  - intent + state chuyển (cho conversation)
  - jira account id, telegram chat id
  - jira issue key khi tạo task
  - reporter summary: số sắp đến hạn, số quá hạn, số assignee đã report
- Cảnh báo:
  - log khi Jira API lỗi
  - log khi file upload thất bại

## 5. Ops procedure
- Khi thêm người mới:
  - bot sẽ yêu cầu `jira_account_id` theo template
  - upsert vào `users.json`
- Khi chỉnh due window / report time:
  - cập nhật config và restart service (để scheduler nạp lại)

## 6. Acceptance criteria
- Bot + scheduler chạy liên tục 24/7.
- `users.json` không bị mất dữ liệu mapping.
- Không gửi report trùng quá mức trong trường hợp service restart (cần policy idempotency từ Phase 6).

