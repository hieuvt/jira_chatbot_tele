# Config Schema (Phase 1 skeleton)

## telegram
- `bot_token`: Telegram bot token.
- `allowed_chat_ids`: list group IDs the bot can serve.
- `attachments.max_files`: max attachments per conversation (default `10`).

## jira
- `base_url`
- `email`
- `api_token`
- `project_key`
- `issue_type_id`
- `subtask_issue_type_id`
- `attachment_max_bytes`
- `http.timeout_seconds` (default `20`)
- `http.retry_count` (default `3`)
- `http.retry_backoff_seconds` (default `1.0`)
- `search.max_results` (default `50`)
- `search.max_pages` (default `20`)
- `timezone` (`Asia/Ho_Chi_Minh`)

## due.notification
- `window_days`
- `report_timezone` (default `Asia/Ho_Chi_Minh`)
- `report_times` (default `["08:00", "17:00"]`)

## conversation
- `timeout_minutes`: conversation timeout in minutes (default `10`).

