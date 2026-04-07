"""Khởi tạo scheduler báo cáo định kỳ: APScheduler nếu có, không thì stub chạy vòng lặp theo giờ."""

from __future__ import annotations

from dataclasses import dataclass, field
from calendar import monthrange
from datetime import datetime
from typing import Any, Callable, Iterable
import threading
import time

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency in Phase 1
    BackgroundScheduler = None


@dataclass
class SchedulerStub:
    """Stub khi không cài APScheduler: thread nền tính next run theo HH:MM mỗi ngày."""
    timezone: str
    started: bool = False
    _jobs: dict[str, tuple[int, int, Callable[..., None], dict[str, Any]]] = field(default_factory=dict)
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        self.started = True
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def add_job(
        self,
        func: Callable[..., None],
        *,
        trigger: str | None = None,
        hour: int,
        minute: int,
        timezone: str | None = None,
        id: str | None = None,
        replace_existing: bool = False,
        **kwargs: object,
    ) -> None:
        _ = (trigger, timezone, replace_existing)
        job_id = id or f"job_{hour:02d}{minute:02d}"
        run_kwargs = kwargs.get("kwargs", {})
        if not isinstance(run_kwargs, dict):
            run_kwargs = {}
        self._jobs[job_id] = (hour, minute, func, dict(run_kwargs))

    def _run_loop(self) -> None:
        # Scheduler nhẹ khi không có APScheduler
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            tz = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            # Thiếu tzdata: HCM cố định UTC+7; còn lại dùng UTC
            if str(self.timezone).lower() == "asia/ho_chi_minh":
                tz = timezone(timedelta(hours=7))
            else:
                tz = timezone.utc
        while not self._stop_event.is_set():
            if not self._jobs:
                time.sleep(30)
                continue

            now = datetime.now(tz=tz)
            next_run: datetime | None = None
            next_job_id: str | None = None
            target_hour: int | None = None
            target_minute: int | None = None

            for job_id, (hour, minute, func, run_kwargs) in self._jobs.items():
                candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= now:
                    candidate = candidate + timedelta(days=1)
                if next_run is None or candidate < next_run:
                    next_run = candidate
                    next_job_id = job_id
                    target_hour = hour
                    target_minute = minute

            if next_run is None or target_hour is None or target_minute is None:
                time.sleep(30)
                continue

            sleep_seconds = (next_run - now).total_seconds()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            executed_count = 0
            for job_id, (hour, minute, func, run_kwargs) in list(self._jobs.items()):
                if hour != target_hour or minute != target_minute:
                    continue
                try:
                    func(**run_kwargs)
                    executed_count += 1
                except Exception:
                    # Không để job làm chết vòng lặp; log do callback tự xử lý
                    pass

    def shutdown(self) -> None:
        self._stop_event.set()


def build_scheduler(timezone: str) -> object:
    """Tạo BackgroundScheduler hoặc SchedulerStub tùy có APScheduler hay không."""
    if BackgroundScheduler is None:
        return SchedulerStub(timezone=timezone)
    scheduler = BackgroundScheduler(timezone=timezone)
    return scheduler


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse chuỗi HH:MM trong config report_times."""
    raw = str(value).strip()
    if not raw or ":" not in raw:
        raise ValueError(f"Invalid time format: {value!r}, expected HH:MM")
    hh, mm = raw.split(":", 1)
    hour = int(hh)
    minute = int(mm)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid HH:MM range: {value!r}")
    return hour, minute


def _parse_day_of_month(value: object) -> int:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Invalid day_of_month: empty")
    day = int(raw)
    if day < 1 or day > 31:
        raise ValueError(f"Invalid day_of_month range: {value!r}")
    return day


def should_run_monthly_today(*, day_of_month: int, now: datetime) -> bool:
    """True khi hôm nay là ngày cấu hình, hoặc là ngày cuối tháng nếu day > số ngày của tháng."""
    if day_of_month < 1 or day_of_month > 31:
        return False
    _, last_day = monthrange(now.year, now.month)
    expected_day = day_of_month if day_of_month <= last_day else last_day
    return now.day == expected_day


def configure_phase5_report_jobs(
    *,
    scheduler: object,
    timezone: str,
    report_times: Iterable[str],
    job_callback: Callable[[], None],
) -> None:
    """
    Đăng ký job cron Phase 5 (N lần/ngày theo `report_times`, timezone từ config).
    Stub scheduler không có add_job thì bỏ qua.
    """
    add_job = getattr(scheduler, "add_job", None)
    if not callable(add_job):
        # Không có APScheduler — stub không schedule được
        return

    for t in report_times:
        hour, minute = _parse_hhmm(t)
        # id ổn định để dev gọi lại không nhân đôi job
        job_id = f"phase5_report_{hour:02d}{minute:02d}"

        add_job(
            job_callback,
            trigger="cron",
            hour=hour,
            minute=minute,
            timezone=timezone,
            id=job_id,
            replace_existing=True,
            # Prevent overlapping executions if a send takes longer than expected.
            max_instances=1,
            coalesce=True,
        )


def configure_monthly_task_jobs(
    *,
    scheduler: object,
    timezone: str,
    monthly_tasks: Iterable[dict[str, object]],
    job_callback: Callable[..., None],
) -> None:
    """
    Đăng ký job định kỳ hàng tháng theo từng task config.
    Lịch trigger chạy mỗi ngày tại `time_of_day`; callback tự quyết định có chạy hôm nay hay không
    bằng `day_of_month` (bao gồm rule ngày cuối tháng).
    """
    add_job = getattr(scheduler, "add_job", None)
    if not callable(add_job):
        return

    for idx, task in enumerate(monthly_tasks):
        if not isinstance(task, dict):
            continue
        try:
            day = _parse_day_of_month(task.get("day_of_month"))
            hour, minute = _parse_hhmm(str(task.get("time_of_day", "")))
        except Exception:
            continue
        job_id = f"monthly_task_{idx}_{hour:02d}{minute:02d}"
        add_job(
            job_callback,
            trigger="cron",
            hour=hour,
            minute=minute,
            timezone=timezone,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            kwargs={"task_index": idx, "day_of_month": day},
        )


