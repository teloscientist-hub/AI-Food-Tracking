from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.summary import DailySummaryRead, WeeklySummaryRead
from app.services.summary_service import SummaryService


router = APIRouter(prefix="/api/summaries", tags=["summaries"])


@router.get("/daily", response_model=DailySummaryRead)
def get_daily_summary(
    target_date: date | None = None, session: Session = Depends(get_session)
) -> DailySummaryRead:
    service = SummaryService()
    return DailySummaryRead.model_validate(service.get_daily_summary(session, target_date or date.today()))


@router.get("/weekly", response_model=WeeklySummaryRead)
def get_weekly_summary(
    target_date: date | None = None,
    metric: str = "calories",
    session: Session = Depends(get_session),
) -> WeeklySummaryRead:
    service = SummaryService()
    return WeeklySummaryRead.model_validate(
        service.get_weekly_summary(session, target_date or date.today(), metric)
    )

