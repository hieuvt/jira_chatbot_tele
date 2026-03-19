"""Validation helpers for conversation steps."""


def parse_due_days(raw_value: str) -> int:
    text = raw_value.strip()
    if not text.isdigit():
        raise ValueError("DueDays must be a positive integer.")
    value = int(text)
    if value <= 0:
        raise ValueError("DueDays must be greater than zero.")
    return value


def parse_checklist_line(raw_value: str) -> str | None:
    line = raw_value.strip()
    if not line:
        return None
    if line.lower() == "không":
        return None
    return line

