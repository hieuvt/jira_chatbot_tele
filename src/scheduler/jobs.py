"""Scheduler bootstrap for periodic reports (skeleton)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable
import threading
import time

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency in Phase 1
    BackgroundScheduler = None


@dataclass
class SchedulerStub:
    timezone: str
    started: bool = False
    _jobs: dict[str, tuple[int, int, Callable[[], None]]] = field(default_factory=dict)
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
        func: Callable[[], None],
        *,
        trigger: str | None = None,
        hour: int,
        minute: int,
        timezone: str | None = None,
        id: str | None = None,
        replace_existing: bool = False,
        **kwargs: object,
    ) -> None:
        _ = (trigger, timezone, replace_existing, kwargs)
        job_id = id or f"job_{hour:02d}{minute:02d}"
        self._jobs[job_id] = (hour, minute, func)

    def _run_loop(self) -> None:
        # Lightweight daily scheduler used when APScheduler is unavailable.
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            tz = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            # Fallback for environments without tzdata package.
            # Asia/Ho_Chi_Minh is fixed offset UTC+07 without DST.
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
            next_func: Callable[[], None] | None = None

            for _, (hour, minute, func) in self._jobs.items():
                candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= now:
                    candidate = candidate + timedelta(days=1)
                if next_run is None or candidate < next_run:
                    next_run = candidate
                    next_func = func

            if next_run is None or next_func is None:
                time.sleep(30)
                continue

            sleep_seconds = (next_run - now).total_seconds()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            try:
                next_func()
            except Exception:
                # Fail-safe: don't kill scheduling loop.
                # Actual logging is handled by the job callback itself.
                pass

    def shutdown(self) -> None:
        self._stop_event.set()


def build_scheduler(timezone: str) -> object:
    """Build scheduler object.

    Use APScheduler when available; fallback to stub otherwise.
    """
    if BackgroundScheduler is None:
        return SchedulerStub(timezone=timezone)
    scheduler = BackgroundScheduler(timezone=timezone)
    return scheduler


def _parse_hhmm(value: str) -> tuple[int, int]:
    raw = str(value).strip()
    if not raw or ":" not in raw:
        raise ValueError(f"Invalid time format: {value!r}, expected HH:MM")
    hh, mm = raw.split(":", 1)
    hour = int(hh)
    minute = int(mm)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"Invalid HH:MM range: {value!r}")
    return hour, minute


def configure_phase5_report_jobs(
    *,
    scheduler: object,
    timezone: str,
    report_times: Iterable[str],
    job_callback: Callable[[], None],
) -> None:
    """
    Schedule Phase 5 report jobs using APScheduler cron trigger.

    Contract:
    - Run 2x/day (or N times) per `report_times` list.
    - Use `timezone` for cron calculation.
    """
    add_job = getattr(scheduler, "add_job", None)
    if not callable(add_job):
        # APScheduler dependency missing -> scheduler is a stub; no jobs can be scheduled.
        return

    for t in report_times:
        hour, minute = _parse_hhmm(t)
        # Stable-ish job id so multiple calls won't create duplicates in development.
        job_id = f"phase5_report_{hour:02d}{minute:02d}"

        add_job(
            job_callback,
            trigger="cron",
            hour=hour,
            minute=minute,
            timezone=timezone,
            id=job_id,
            replace_existing=True,
        )


