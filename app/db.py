from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_sqlite_compat_migrations()


def _run_sqlite_compat_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "health_goals" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("health_goals")}
    desired_columns = {
        "current_weight_lb": "ALTER TABLE health_goals ADD COLUMN current_weight_lb FLOAT",
        "current_body_fat_pct": "ALTER TABLE health_goals ADD COLUMN current_body_fat_pct FLOAT",
        "current_lean_body_mass_lb": "ALTER TABLE health_goals ADD COLUMN current_lean_body_mass_lb FLOAT",
        "current_exercise_minutes": "ALTER TABLE health_goals ADD COLUMN current_exercise_minutes FLOAT",
    }
    with engine.begin() as connection:
        for column_name, ddl in desired_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(ddl))


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
