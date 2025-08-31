# domain.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, time

@dataclass
class WorkShift:
    """Represents a single work day entry."""
    work_date: date
    start_time: time
    end_time: time
    break_minutes: int = 0
    hours_worked: float = 0.0
    overtime_hours: float = 0.0
    notes: str | None = None

    @property
    def iso_year_week(self) -> tuple[int, int]:
        """Returns (ISO year, ISO week number). Useful for weekly overtime aggregation."""
        iso = self.work_date.isocalendar()
        return (iso[0], iso[1])
