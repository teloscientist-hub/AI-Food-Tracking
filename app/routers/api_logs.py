from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.logging import LogMealRequest
from app.services.logging_service import LoggingService


router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.post("")
def create_log_endpoint(payload: LogMealRequest, session: Session = Depends(get_session)) -> dict:
    service = LoggingService()
    try:
        meal_entry = service.save_meal(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"meal_entry_id": meal_entry.id}

