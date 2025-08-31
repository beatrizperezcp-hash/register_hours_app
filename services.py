# services.py
from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import Iterable, Dict, Tuple
from domain import WorkShift

class WorkHoursCalculator:
    """Business rules for calculating worked hours and overtime."""
    def __init__(self, daily_threshold: float = 8.0, weekly_threshold: float = 40.0):
        self.daily_threshold = daily_threshold
        self.weekly_threshold = weekly_threshold

    def calculate_hours_worked(self, start: time, end: time, break_minutes: int = 0) -> float:
        """Returns worked hours (2 decimals). Supports overnight shifts."""
        t0 = datetime.combine(date.today(), start)
        t1 = datetime.combine(date.today(), end)
        if t1 < t0:
            t1 += timedelta(days=1)  # passed midnight
        total = (t1 - t0).total_seconds() / 3600.0
        total -= max(0, break_minutes) / 60.0
        return round(max(0.0, total), 2)

    def calculate_daily_overtime(self, hours_worked: float) -> float:
        """Overtime above the daily threshold."""
        # TODO: adapt this if your company counts overtime differently
        return round(max(0.0, hours_worked - self.daily_threshold), 2)

    def calculate_weekly_overtime(self, shifts: Iterable[WorkShift]) -> Dict[Tuple[int, int], float]:
        """
        Aggregates overtime per ISO week.
        Returns dict {(year, week): overtime_hours}.
        """
        weekly_hours: Dict[Tuple[int, int], float] = {}
        for s in shifts:
            key = s.iso_year_week
            weekly_hours[key] = weekly_hours.get(key, 0.0) + s.hours_worked

        weekly_overtime: Dict[Tuple[int, int], float] = {}
        for k, total in weekly_hours.items():
            weekly_overtime[k] = round(max(0.0, total - self.weekly_threshold), 2)
        return weekly_overtime

    def complete_shift(self, shift: WorkShift) -> WorkShift:
        """Fills in hours worked and overtime for a given shift."""
        shift.hours_worked = self.calculate_hours_worked(
            shift.start_time, shift.end_time, shift.break_minutes
        )
        shift.overtime_hours = self.calculate_daily_overtime(shift.hours_worked)
        return shift
