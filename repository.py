# repository.py
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

def build_engine(db_url: str, echo: bool = False):
    is_sqlite = db_url.startswith("sqlite")
    kwargs = {
        "echo": echo,
        "pool_pre_ping": True,   # importante para autosuspend
        "future": True,
        "connect_args": {},
    }
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Serverless PG: sin pool local y con SSL
        kwargs["poolclass"] = NullPool
        # Si la URL no trae sslmode, lo forzamos (Neon lo requiere)
        if "sslmode=" not in db_url:
            db_url = db_url + ("&" if "?" in db_url else "?") + "sslmode=require"
        kwargs["connect_args"] = {"connect_timeout": 10}

    return create_engine(db_url, **kwargs)

class WorkShiftRepository:
    """CRUD para turnos. PRODUCCIÓN: no hacer fallback a SQLite."""
    def __init__(self, url: str = "sqlite:///workhours.db", echo: bool = False):
        self.primary_url = url
        self.engine = build_engine(url, echo=echo)

        # Si es Postgres, validamos conexión (fail-fast si falla)
        if not url.startswith("sqlite"):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("select 1"))
            except Exception as e:
                raise RuntimeError(f"No se pudo conectar a Postgres: {e}")

        SQLModel.metadata.create_all(self.engine)
