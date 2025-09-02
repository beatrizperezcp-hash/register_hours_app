# repository.py
class WorkShiftRepository:
    def __init__(self, url: str, echo: bool = False):
        self.primary_url = url
        self.engine = build_engine(url, echo=echo)

        if not url.startswith("sqlite"):
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("select 1"))
            except Exception as e:
                # ❌ antes: fallback a SQLite
                raise RuntimeError(f"No se pudo conectar a Postgres: {e}")  # fail-fast
        SQLModel.metadata.create_all(self.engine)
