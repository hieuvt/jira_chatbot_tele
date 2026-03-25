"""Client Jira Cloud REST (urllib): member/admin, tạo issue/sub-task, upload file, search JQL báo cáo."""

from __future__ import annotations

import base64
import json
import random
import time
import uuid
from datetime import date, datetime, timedelta
from urllib import error, parse, request

from src.common.errors import JiraClientError
from src.jira.models import (
    AttachmentMeta,
    IssueCreateRequest,
    JiraIssueRecord,
    QueryIssuesRequest,
    SubtaskCreateRequest,
)


class JiraClient:
    """Gọi API Jira bằng Basic auth (email + API token service account)."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        timeout_seconds: int = 20,
        retry_count: int = 3,
        retry_backoff_seconds: float = 1.0,
        attachment_max_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.retry_backoff_seconds = retry_backoff_seconds
        self.attachment_max_bytes = attachment_max_bytes
        auth_raw = f"{email}:{api_token}".encode("utf-8")
        self._auth_header = f"Basic {base64.b64encode(auth_raw).decode('ascii')}"

    # --- Quyền & vai trò project ---

    def check_project_membership(self, jira_account_id: str, project_key: str) -> bool:
        self._ensure_bot_has_project_permission(project_key=project_key, permission_key="BROWSE_PROJECTS")
        role_members = self._get_project_role_members(project_key=project_key)
        return jira_account_id in role_members

    def check_project_admin(self, jira_account_id: str, project_key: str) -> bool:
        self._ensure_bot_has_project_permission(project_key=project_key, permission_key="ADMINISTER_PROJECTS")
        for role_name, actors in self._get_project_role_members_with_role_name(project_key).items():
            if "admin" not in role_name.lower():
                continue
            if jira_account_id in actors:
                return True
        return False

    # --- Tạo issue / sub-task / đính kèm ---

    def create_issue(self, request_data: IssueCreateRequest) -> str:
        payload = {
            "fields": {
                "project": {"key": request_data.project_key},
                "issuetype": {"id": request_data.issue_type_id},
                "summary": request_data.summary,
                "description": self._to_adf_text(request_data.description),
                "assignee": {"accountId": request_data.assignee_account_id},
                "duedate": self._validate_due_date(request_data.due_date),
            }
        }
        body = self._request_json("POST", "/rest/api/3/issue", payload=payload)
        issue_key = str(body.get("key", "")).strip()
        if not issue_key:
            raise JiraClientError(
                code="JIRA_CREATE_ISSUE_MISSING_KEY",
                message="Jira create issue response does not contain issue key.",
                context={"project_key": request_data.project_key},
                retriable=False,
            )
        return issue_key

    def create_subtasks(self, request_data: SubtaskCreateRequest) -> list[str]:
        if len(request_data.checklist_items) > 20:
            raise JiraClientError(
                code="JIRA_SUBTASK_LIMIT_EXCEEDED",
                message="Subtask count exceeds Phase 2 limit.",
                context={"limit": 20, "received": len(request_data.checklist_items)},
                retriable=False,
            )
        created_keys: list[str] = []
        errors: list[dict[str, object]] = []
        project_key_from_parent = request_data.parent_issue_key.split("-", 1)[0].strip()
        for item in request_data.checklist_items:
            summary = item.strip()
            if not summary:
                continue
            payload = {
                "fields": {
                    "project": {"key": project_key_from_parent},
                    "parent": {"key": request_data.parent_issue_key},
                    "issuetype": {"id": request_data.issue_type_id},
                    "summary": summary,
                }
            }
            try:
                body = self._request_json("POST", "/rest/api/3/issue", payload=payload)
                issue_key = str(body.get("key", "")).strip()
                if issue_key:
                    created_keys.append(issue_key)
                    continue
                errors.append({"summary": summary, "error": "Missing issue key"})
            except JiraClientError as exc:
                errors.append(
                    {
                        "summary": summary,
                        "error_code": exc.code,
                        "message": exc.message,
                        "context": exc.context,
                    }
                )
        if errors:
            raise JiraClientError(
                code="JIRA_SUBTASK_PARTIAL_FAILURE",
                message="One or more subtasks failed to create.",
                context={"parent_issue_key": request_data.parent_issue_key, "created_keys": created_keys, "errors": errors},
                retriable=False,
            )
        return created_keys

    def upload_attachments(self, issue_key: str, files: list[AttachmentMeta]) -> list[str]:
        uploaded: list[str] = []
        errors: list[dict[str, object]] = []
        for file_data in files:
            if file_data.size_bytes > self.attachment_max_bytes:
                errors.append(
                    {
                        "filename": file_data.filename,
                        "code": "JIRA_ATTACHMENT_TOO_LARGE",
                        "size_bytes": file_data.size_bytes,
                        "max_bytes": self.attachment_max_bytes,
                    }
                )
                continue
            if len(file_data.content_bytes) != file_data.size_bytes:
                errors.append(
                    {
                        "filename": file_data.filename,
                        "code": "JIRA_ATTACHMENT_SIZE_MISMATCH",
                        "size_bytes": file_data.size_bytes,
                        "actual_bytes": len(file_data.content_bytes),
                    }
                )
                continue
            try:
                result = self._upload_single_attachment(issue_key=issue_key, file_data=file_data)
                uploaded.extend(result)
            except JiraClientError as exc:
                errors.append({"filename": file_data.filename, "code": exc.code, "message": exc.message})
        if errors:
            raise JiraClientError(
                code="JIRA_ATTACHMENT_FAIL_ALL",
                message="Attachment upload failed for one or more files.",
                context={"issue_key": issue_key, "uploaded": uploaded, "errors": errors},
                retriable=False,
            )
        return uploaded

    # --- Search & báo cáo due date ---

    def query_issues_by_due_date_for_reporter(
        self, query: QueryIssuesRequest
    ) -> dict[str, list[JiraIssueRecord]]:
        end_time = query.now + timedelta(days=query.window_days)
        jql = (
            f'project = "{query.project_key}" '
            f'AND duedate IS NOT EMPTY '
            f'AND duedate <= "{end_time.strftime("%Y-%m-%d")}"'
        )
        grouped: dict[str, list[JiraIssueRecord]] = {}
        start_at = 0
        for _ in range(query.max_pages):
            params = {
                "jql": jql,
                "fields": "summary,assignee,duedate,status,project,issuetype",
                "startAt": str(start_at),
                "maxResults": str(query.max_results),
            }
            response = self._request_json("GET", "/rest/api/3/search/jql", params=params)
            issues = response.get("issues", [])
            if not isinstance(issues, list):
                break
            for issue in issues:
                record = self._to_issue_record(issue)
                if (record.status_category_key or "").strip().lower() == "done":
                    continue
                if not self._in_due_window(record_due_date=record.due_date, now=query.now, window_days=query.window_days):
                    continue
                group_key = record.assignee_account_id or "unassigned"
                grouped.setdefault(group_key, []).append(record)
            total = int(response.get("total", 0))
            start_at += query.max_results
            if start_at >= total or not issues:
                break
        return grouped

    # --- Nội bộ: quyền bot, role actors, HTTP, lỗi, ADF, multipart ---

    def _ensure_bot_has_project_permission(self, project_key: str, permission_key: str) -> None:
        response = self._request_json(
            "GET",
            "/rest/api/3/mypermissions",
            params={"projectKey": project_key, "permissions": permission_key},
        )
        permissions = response.get("permissions", {})
        permission = permissions.get(permission_key, {}) if isinstance(permissions, dict) else {}
        if bool(permission.get("havePermission")):
            return
        raise JiraClientError(
            code="JIRA_PERMISSION_DENIED",
            message=f"Service account lacks required permission: {permission_key}.",
            context={"project_key": project_key, "permission_key": permission_key},
            retriable=False,
        )

    def _get_project_role_members(self, project_key: str) -> set[str]:
        roles_with_names = self._get_project_role_members_with_role_name(project_key=project_key)
        merged: set[str] = set()
        for members in roles_with_names.values():
            merged.update(members)
        return merged

    def _get_project_role_members_with_role_name(self, project_key: str) -> dict[str, set[str]]:
        role_map = self._request_json("GET", f"/rest/api/3/project/{parse.quote(project_key)}/role")
        if not isinstance(role_map, dict):
            return {}
        result: dict[str, set[str]] = {}
        for role_name, role_url in role_map.items():
            if not isinstance(role_name, str) or not isinstance(role_url, str):
                continue
            role_path = self._relative_path_from_role_url(role_url)
            role_detail = self._request_json("GET", role_path)
            actors = role_detail.get("actors", [])
            result[role_name] = self._extract_account_ids_from_actors(actors=actors)
        return result

    def _upload_single_attachment(self, issue_key: str, file_data: AttachmentMeta) -> list[str]:
        boundary = f"----JiraChatbotTeleBoundary{uuid.uuid4().hex}"
        body = self._build_multipart_body(boundary=boundary, file_data=file_data)
        response = self._request_json(
            "POST",
            f"/rest/api/3/issue/{parse.quote(issue_key)}/attachments",
            data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            extra_headers={"X-Atlassian-Token": "no-check"},
        )
        if not isinstance(response, list):
            raise JiraClientError(
                code="JIRA_ATTACHMENT_INVALID_RESPONSE",
                message="Unexpected attachment response from Jira.",
                context={"issue_key": issue_key},
                retriable=False,
            )
        uploaded_ids: list[str] = []
        for item in response:
            if not isinstance(item, dict):
                continue
            attachment_id = str(item.get("id", "")).strip()
            if attachment_id:
                uploaded_ids.append(attachment_id)
        if not uploaded_ids:
            raise JiraClientError(
                code="JIRA_ATTACHMENT_MISSING_ID",
                message="Attachment upload response did not include attachment id.",
                context={"issue_key": issue_key, "filename": file_data.filename},
                retriable=False,
            )
        return uploaded_ids

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        final_path = path
        if params:
            query = parse.urlencode(params)
            final_path = f"{path}?{query}"
        url = f"{self.base_url}{final_path}"
        body_bytes = data
        if payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        if body_bytes is not None:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = request.Request(url=url, method=method, data=body_bytes, headers=headers)
        for attempt in range(self.retry_count + 1):
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8")
                    if not raw:
                        return {}
                    return json.loads(raw)
            except error.HTTPError as exc:
                retriable = exc.code in {429, 500, 502, 503, 504}
                if retriable and attempt < self.retry_count:
                    self._sleep_retry(attempt=attempt, retry_after=exc.headers.get("Retry-After"))
                    continue
                raise self._map_http_error(exc=exc, path=path) from exc
            except error.URLError as exc:
                if attempt < self.retry_count:
                    self._sleep_retry(attempt=attempt, retry_after=None)
                    continue
                raise JiraClientError(
                    code="JIRA_NETWORK_ERROR",
                    message=f"Network error while calling Jira: {exc.reason}",
                    context={"path": path},
                    retriable=True,
                ) from exc
            except json.JSONDecodeError as exc:
                raise JiraClientError(
                    code="JIRA_INVALID_JSON",
                    message="Jira returned invalid JSON response.",
                    context={"path": path},
                    retriable=False,
                ) from exc
        raise JiraClientError(
            code="JIRA_UNKNOWN_ERROR",
            message="Unexpected Jira request flow termination.",
            context={"path": path},
            retriable=False,
        )

    def _map_http_error(self, exc: error.HTTPError, path: str) -> JiraClientError:
        payload = self._try_read_error_payload(exc)
        context = {"path": path, "status": exc.code, "jira_error": payload}
        if exc.code in {401, 403}:
            return JiraClientError("JIRA_AUTH_OR_PERMISSION", "Authentication or permission denied.", context, False)
        if exc.code == 404:
            return JiraClientError("JIRA_NOT_FOUND", "Jira resource not found.", context, False)
        if exc.code == 400:
            return JiraClientError("JIRA_BAD_REQUEST", "Invalid request payload for Jira.", context, False)
        if exc.code == 429:
            return JiraClientError("JIRA_RATE_LIMITED", "Jira rate limit exceeded.", context, True)
        if exc.code >= 500:
            return JiraClientError("JIRA_SERVER_ERROR", "Jira server error.", context, True)
        return JiraClientError("JIRA_HTTP_ERROR", f"Jira HTTP error: {exc.code}", context, False)

    def _try_read_error_payload(self, exc: error.HTTPError) -> dict[str, object] | str:
        try:
            raw = exc.read().decode("utf-8")
        except Exception:
            return ""
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return raw

    def _sleep_retry(self, attempt: int, retry_after: str | None) -> None:
        if retry_after and retry_after.isdigit():
            wait_seconds = float(retry_after)
        else:
            wait_seconds = self.retry_backoff_seconds * (2**attempt)
            wait_seconds += random.uniform(0.0, 0.3)
        time.sleep(wait_seconds)

    def _to_adf_text(self, text: str) -> dict[str, object]:
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }

    def _validate_due_date(self, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise JiraClientError(
                code="JIRA_INVALID_DUE_DATE",
                message="Due date must follow YYYY-MM-DD format.",
                context={"due_date": value},
                retriable=False,
            ) from exc
        return value

    def _relative_path_from_role_url(self, role_url: str) -> str:
        parsed = parse.urlparse(role_url)
        if parsed.path.startswith("/"):
            path = parsed.path
        else:
            path = f"/{parsed.path}"
        if parsed.query:
            return f"{path}?{parsed.query}"
        return path

    def _extract_account_ids_from_actors(self, actors: object) -> set[str]:
        if not isinstance(actors, list):
            return set()
        result: set[str] = set()
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            actor_user = actor.get("actorUser")
            if isinstance(actor_user, dict):
                account_id = str(actor_user.get("accountId", "")).strip()
                if account_id:
                    result.add(account_id)
                    continue
            account_id = str(actor.get("accountId", "")).strip()
            if account_id:
                result.add(account_id)
        return result

    def _build_multipart_body(self, *, boundary: str, file_data: AttachmentMeta) -> bytes:
        lines: list[bytes] = [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{file_data.filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {file_data.content_type}\r\n\r\n".encode("utf-8"),
            file_data.content_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        return b"".join(lines)

    def _to_issue_record(self, issue: object) -> JiraIssueRecord:
        if not isinstance(issue, dict):
            return JiraIssueRecord("", "", None, "", None)
        fields = issue.get("fields", {}) if isinstance(issue.get("fields"), dict) else {}
        assignee = fields.get("assignee", {}) if isinstance(fields.get("assignee"), dict) else {}
        status = fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}
        st_cat = status.get("statusCategory", {}) if isinstance(status.get("statusCategory"), dict) else {}
        return JiraIssueRecord(
            issue_key=str(issue.get("key", "")).strip(),
            summary=str(fields.get("summary", "")).strip(),
            due_date=str(fields.get("duedate", "")).strip() or None,
            status=str(status.get("name", "")).strip(),
            assignee_account_id=str(assignee.get("accountId", "")).strip() or None,
            status_category_key=str(st_cat.get("key", "")).strip().lower(),
        )

    def _in_due_window(self, *, record_due_date: str | None, now: datetime, window_days: int) -> bool:
        if not record_due_date:
            return False
        try:
            due_date = date.fromisoformat(record_due_date)
        except ValueError:
            return False
        due_at = datetime.combine(due_date, datetime.min.time(), tzinfo=now.tzinfo)
        upper_bound = now + timedelta(days=window_days)
        return due_at <= upper_bound

