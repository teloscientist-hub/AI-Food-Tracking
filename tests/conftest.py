from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import DailyTarget


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
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

