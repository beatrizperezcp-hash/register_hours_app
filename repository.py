# repository.py
from __future__ import annotations

from typing import List
from datetime import date, time

from sqlalchemy.pool import NullPool
from sqlalchemy import text
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
    Crea el engine para SQLite o Postgres (Supabase).
    - SQLite: check_same_thread=False para uso con Streamlit.
    - Postgres/Supabase: NullPool (el pooling lo hace PgBouncer o el servidor) + pool_pre_ping.
      Asegúrate de que la URL lleve sslmode=require y, si usas Transaction Pooler,
      desactiva prepared statements con statement_cache_size=0 (vía options en la URL).
    """
    is_sqlite = db_url.startswith("sqlite")
    kwargs = {"echo": echo, "pool_pre_ping": True, "future": True}

    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Postgres (incluye Supabase): deja el pooling al pooler/servidor
        kwargs["poolclass"] = NullPool

    return create_engine(db_url, **kwargs)


class WorkShiftRepository:
    """CRUD para turnos de trabajo. Compatible con SQLite y Postgres."""
    def __init__(self, url: str = "sqlite:///workhours.db", echo: bool = False):
        self.engine = build_engine(url, echo=echo)
        is_sqlite = url.startswith("sqlite")

        if is_sqlite:
            # En SQLite siempre podemos crear el esquema local
            SQLModel.metadata.create_all(self.engine)
        else:
            # En Postgres: intenta conectar y crear esquema, pero no derribes la app si falla
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("select 1"))
                SQLModel.metadata.create_all(self.engine)
            except Exception as e:
                # No interrumpas el arranque; la UI mostrará el error en la barra lateral
                print("⚠️  Aviso: no se pudo conectar/crear tablas en la BD remota:", repr(e))

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
