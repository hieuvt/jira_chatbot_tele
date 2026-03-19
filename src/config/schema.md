# Config Schema (Phase 1 skeleton)

## telegram
- `bot_token`: Telegram bot token.
- `allowed_chat_ids`: list group IDs the bot can serve.

## jira
- `base_url`
- `email`
- `api_token`
- `project_key`
- `issue_type_key`
- `subtask_issue_type_key`
- `admin_project_role_name` (default `Administrators`)
- `attachment_max_bytes`

## due.notification
- `window_days`
- `report_timezone` (default `Asia/Ho_Chi_Minh`)
- `report_times` (default `["08:00", "17:00"]`)

