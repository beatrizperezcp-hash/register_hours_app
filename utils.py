# utils.py
import pandas as pd
from typing import Iterable
from domain import WorkShift

def shifts_to_dataframe(shifts: Iterable[WorkShift]) -> pd.DataFrame:
    rows = []
    for s in shifts:
        year, week = s.iso_year_week
        rows.append({
            "Date": s.work_date.isoformat(),
            "ISO Week": f"{year}-W{week:02d}",
            "Start": s.start_time.strftime("%H:%M"),
            "End": s.end_time.strftime("%H:%M"),
            "Break (min)": s.break_minutes,
            "Hours Worked": s.hours_worked,
            "Overtime (daily)": s.overtime_hours,
            "Notes": s.notes or ""
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Date"], ascending=False).reset_index(drop=True)
    return df
