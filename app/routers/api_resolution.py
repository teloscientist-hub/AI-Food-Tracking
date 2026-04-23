from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import MealEntryItem
from app.services.logging_service import LoggingService


router = APIRouter(tags=["resolution"])


class ResolvePhraseRequest(BaseModel):
    phrase: str


@router.post("/api/resolve")
def resolve_phrase_endpoint(
    payload: ResolvePhraseRequest, session: Session = Depends(get_session)
) -> dict:
    service = LoggingService()
    review = service.build_review(session, payload.phrase)
    return {
        "items": [
            {
                "parsed_phrase": item.parsed_item.phrase,
                "quantity": item.parsed_item.quantity,
                "unit": item.parsed_item.unit,
                "status": item.status,
                "chosen": asdict(item.chosen) if item.chosen else None,
                "candidates": [asdict(candidate) for candidate in item.candidates],
            }
            for item in review
        ]
    }


@router.get("/api/unresolved")
def list_unresolved(session: Session = Depends(get_session)) -> dict:
    items = session.scalars(
        select(MealEntryItem).where(MealEntryItem.resolution_status != "resolved")
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "parsed_phrase": item.parsed_phrase,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]
    }
