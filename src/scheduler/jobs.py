"""Scheduler bootstrap for periodic reports (skeleton)."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency in Phase 1
    BackgroundScheduler = None


@dataclass
class SchedulerStub:
    timezone: str
    started: bool = False

    def start(self) -> None:
        self.started = True


def build_scheduler(timezone: str) -> object:
    """Build scheduler object.

    Use APScheduler when available; fallback to stub otherwise.
    """
    if BackgroundScheduler is None:
        return SchedulerStub(timezone=timezone)
    scheduler = BackgroundScheduler(timezone=timezone)
    return scheduler

