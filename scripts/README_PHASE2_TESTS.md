# Phase 2 Test Scripts

## 1) Compile check

```powershell
python -m py_compile src/jira/client.py src/jira/models.py src/common/errors.py src/jira/permissions.py
```

## 2) Smoke test (end-to-end)

```powershell
python scripts/phase2_smoke_test.py --assignee-account-id "<ASSIGNEE_ACCOUNT_ID>" --reporter-account-id "<REPORTER_ACCOUNT_ID>"
```

Optional:

```powershell
python scripts/phase2_smoke_test.py --assignee-account-id "<ASSIGNEE_ACCOUNT_ID>" --reporter-account-id "<REPORTER_ACCOUNT_ID>" --skip-upload
```

## 3) Negative tests

```powershell
python scripts/phase2_negative_test.py --assignee-account-id "<ASSIGNEE_ACCOUNT_ID>"
```
