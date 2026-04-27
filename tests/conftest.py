from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

import app.main as main_module
from app.db import Base, get_session
from app.models import DailyTarget


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        session.add(
            DailyTarget(
                target_date=date.today(),
                calories_target=2200,
                protein_target_g=180,
                carbs_target_g=150,
                fat_target_g=80,
                fiber_target_g=30,
                net_carbs_target_g=120,
            )
        )
        session.commit()
        yield session


@pytest.fixture()
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def override_get_session():
        yield session

    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "seed_demo_data", lambda _session: None)
    main_module.app.dependency_overrides[get_session] = override_get_session
    with TestClient(main_module.app) as test_client:
        yield test_client
    main_module.app.dependency_overrides.clear()
