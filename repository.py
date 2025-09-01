# repository.py
from __future__ import annotations

from typing import List
from datetime import date, time

from sqlalchemy.pool import NullPool
from sqlalchemy import text
from sqlmodel import SQLModel, Field, Session, create_engine, select

from domain import WorkShift

class WorkShiftDB(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    work_date: date = Field(index=True)
    start_time: time
    end_time: time
    break_minutes: int
    hours_worked: float
    overtime_hours: float
    notes: str | None = None

def build_engine(db_url: str, echo: bool = False):
    is_sqlite = db_url.startswith("sqlite")
    kwargs = {
        "echo": echo,
        "pool_pre_ping": True,
        "future": True,
        "connect_args": {},
    }
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Deja el pooling al pooler (PgBouncer)
        kwargs["poolclass"] = NullPool
        # timeouts para fallar rápido si la red no deja
        kwargs["connect_args"] = {"connect_timeout": 10}
    return create_engine(db_url, **kwargs)

class WorkShiftRepository:
    """CRUD para turnos. Intenta Postgres y si falla, cae a SQLite."""
    def __init__(self, url: str = "sqlite:///workhours.db", echo: bool = False):
        self.primary_url = url
        self.engine = build_engine(url, echo=echo)

        # 1) Intento de conexión si NO es sqlite
        if not url.startswith("sqlite"):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("select 1"))
            except Exception as e:
                # 2) Fallback a SQLite en ./data/workhours.db
                from pathlib import Path
                data_dir = Path("./data")
                data_dir.mkdir(parents=True, exist_ok=True)
                fallback_url = f"sqlite:///{(data_dir / 'workhours.db').as_posix()}"
                self.engine = build_engine(fallback_url, echo=False)

        # Crea tablas si no existen (en el engine activo)
        SQLModel.metadata.create_all(self.engine)

    def add(self, s: WorkShift) -> None:
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
