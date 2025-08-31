# repository.py
from __future__ import annotations

from typing import List
from datetime import date, time

from sqlmodel import SQLModel, Field, Session, create_engine, select
from domain import WorkShift


class WorkShiftDB(SQLModel, table=True):
    # Nota: el nombre de la tabla por defecto será "workshiftdb"
    id: int | None = Field(default=None, primary_key=True)
    work_date: date = Field(index=True)
    start_time: time
    end_time: time
    break_minutes: int
    hours_worked: float
    overtime_hours: float
    notes: str | None = None


def build_engine(db_url: str, echo: bool = False):
    """
    Crea el engine para SQLite o Postgres.
    - SQLite: check_same_thread=False para uso con Streamlit.
    - Postgres/otros: pool_pre_ping para conexiones saludables.
    """
    kwargs = {"echo": echo, "pool_pre_ping": True, "future": True}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(db_url, **kwargs)


class WorkShiftRepository:
    """CRUD para turnos de trabajo. Compatible con SQLite y Postgres."""
    def __init__(self, url: str = "sqlite:///workhours.db", echo: bool = False):
        self.engine = build_engine(url, echo=echo)
        SQLModel.metadata.create_all(self.engine)

    def add(self, s: WorkShift) -> None:
        """Inserta un registro de trabajo."""
        with Session(self.engine) as session:
            row = WorkShiftDB(
                work_date=s.work_date,
                start_time=s.start_time,
                end_time=s.end_time,
                break_minutes=s.break_minutes,
                hours_worked=s.hours_worked,
                overtime_hours=s.overtime_hours,
                notes=s.notes,
            )
            session.add(row)
            session.commit()

    def list_all(self) -> List[WorkShift]:
        """Devuelve todos los registros (últimos primero)."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(WorkShiftDB).order_by(WorkShiftDB.work_date.desc(), WorkShiftDB.id.desc())
            ).all()
            return [
                WorkShift(
                    work_date=r.work_date,
                    start_time=r.start_time,
                    end_time=r.end_time,
                    break_minutes=r.break_minutes,
                    hours_worked=r.hours_worked,
                    overtime_hours=r.overtime_hours,
                    notes=r.notes,
                )
                for r in rows
            ]
