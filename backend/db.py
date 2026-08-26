"""Database engine + session helpers.

Runs on SQLite (default, zero-config) and Postgres (Supabase or a container in
the compose stack) from the same DATABASE_URL. The engine arguments are NOT the
same for both, so they are chosen by dialect rather than passed unconditionally:

  sqlite    check_same_thread=False   FastAPI serves requests on a threadpool,
                                      and SQLite otherwise refuses a connection
                                      used off the thread that opened it.
                                      Passing this to psycopg is a TypeError at
                                      connect time, not a warning.

  postgres  pool_pre_ping=True        Supabase's pooler and any idle-timeout in
                                      front of Postgres drop connections that
                                      the pool still believes are live. Without
                                      the ping the first request after an idle
                                      period fails with a closed-connection
                                      error rather than reconnecting.
            pool_recycle=1800         Second belt: retire connections before an
                                      upstream idle timeout can.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DATA_DIR / 'signal.db'}"

# `postgres://` is what Supabase and Heroku hand out; SQLAlchemy 2 only accepts
# `postgresql://`. Rewriting here means a pasted connection string just works.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

DIALECT = make_url(DATABASE_URL).get_backend_name()
IS_SQLITE = DIALECT == "sqlite"


def _engine_kwargs() -> dict[str, Any]:
    if IS_SQLITE:
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True, "pool_recycle": 1800}


engine = create_engine(DATABASE_URL, echo=False, **_engine_kwargs())


def init_db() -> None:
    import models  # noqa: F401  (registers tables on SQLModel.metadata)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
