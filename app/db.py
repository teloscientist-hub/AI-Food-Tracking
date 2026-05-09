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
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "health_goals" in table_names:
            existing_columns = {column["name"] for column in inspector.get_columns("health_goals")}
            desired_columns = {
                "current_weight_lb": "ALTER TABLE health_goals ADD COLUMN current_weight_lb FLOAT",
                "current_body_fat_pct": "ALTER TABLE health_goals ADD COLUMN current_body_fat_pct FLOAT",
                "current_lean_body_mass_lb": "ALTER TABLE health_goals ADD COLUMN current_lean_body_mass_lb FLOAT",
                "current_exercise_minutes": "ALTER TABLE health_goals ADD COLUMN current_exercise_minutes FLOAT",
            }
            for column_name, ddl in desired_columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(ddl))
        if "foods" in table_names:
            food_columns = {column["name"] for column in inspector.get_columns("foods")}
            if "image_url" not in food_columns:
                connection.execute(text("ALTER TABLE foods ADD COLUMN image_url VARCHAR(1024)"))
            if "image_content_type" not in food_columns:
                connection.execute(text("ALTER TABLE foods ADD COLUMN image_content_type VARCHAR(128)"))
            if "image_data" not in food_columns:
                connection.execute(text("ALTER TABLE foods ADD COLUMN image_data BLOB"))
            if "icon_key" not in food_columns:
                connection.execute(text("ALTER TABLE foods ADD COLUMN icon_key VARCHAR(64)"))
        if "exercise_checkins" in table_names:
            exercise_columns = {column["name"] for column in inspector.get_columns("exercise_checkins")}
            if "zone2_minutes" not in exercise_columns:
                connection.execute(text("ALTER TABLE exercise_checkins ADD COLUMN zone2_minutes FLOAT"))


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
