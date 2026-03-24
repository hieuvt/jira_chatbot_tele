"""Hàm kiểm tra và parse input theo từng bước hội thoại (due days, có/không/xong, checklist)."""


def parse_due_days(raw_value: str) -> int:
    """Parse số ngày due: chỉ chữ số, phải là số nguyên dương."""
    text = raw_value.strip()
    if not text.isdigit():
        raise ValueError("DueDays must be a positive integer.")
    value = int(text)
    if value <= 0:
        raise ValueError("DueDays must be greater than zero.")
    return value


def normalize_token(raw_value: str) -> str:
    """Chuẩn hoá token người dùng (trim + lower)."""
    return raw_value.strip().lower()


def is_khong(raw_value: str) -> bool:
    """Người dùng chọn bỏ qua / không thêm (tiếng Việt hoặc no)."""
    return normalize_token(raw_value) in {"không", "khong", "no"}


def _normalize_slash_command_token(raw_value: str) -> str:
    """Bỏ hậu tố @bot cho lệnh trong nhóm (vd: /huy@MyBot -> /huy)."""
    token = normalize_token(raw_value)
    if token.startswith("/") and "@" in token:
        return token.split("@", 1)[0]
    return token


def is_huy(raw_value: str) -> bool:
    """Hủy phiên: hủy/huy hoặc lệnh /cancel, /huy."""
    return _normalize_slash_command_token(raw_value) in {"hủy", "huy", "/cancel", "/huy"}


def is_xong(raw_value: str) -> bool:
    """Kết thúc bước upload checklist hoặc file: xong/done."""
    return normalize_token(raw_value) in {"xong", "done", "/done"}


def is_co(raw_value: str) -> bool:
    """Xác nhận tạo việc: có/co/yes."""
    return normalize_token(raw_value) in {"có", "co", "yes"}


def split_checklist_lines(raw_value: str) -> list[str]:
    """Tách checklist theo dòng; bỏ dòng rỗng (không cắt tại 'Không' ở đây — do state_machine xử lý)."""
    values: list[str] = []
    for line in raw_value.splitlines():
        item = line.strip()
        if item:
            values.append(item)
    return values
