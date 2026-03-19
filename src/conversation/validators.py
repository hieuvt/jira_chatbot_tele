"""Validation helpers for conversation steps."""


def parse_due_days(raw_value: str) -> int:
    text = raw_value.strip()
    if not text.isdigit():
        raise ValueError("DueDays must be a positive integer.")
    value = int(text)
    if value <= 0:
        raise ValueError("DueDays must be greater than zero.")
    return value


def normalize_token(raw_value: str) -> str:
    return raw_value.strip().lower()


def is_khong(raw_value: str) -> bool:
    return normalize_token(raw_value) in {"không", "khong", "no"}


def is_huy(raw_value: str) -> bool:
    return normalize_token(raw_value) in {"hủy", "huy", "/cancel"}


def is_xong(raw_value: str) -> bool:
    return normalize_token(raw_value) in {"xong", "done", "/done"}


def is_co(raw_value: str) -> bool:
    return normalize_token(raw_value) in {"có", "co", "yes"}


def split_checklist_lines(raw_value: str) -> list[str]:
    values: list[str] = []
    for line in raw_value.splitlines():
        item = line.strip()
        if item:
            values.append(item)
    return values

