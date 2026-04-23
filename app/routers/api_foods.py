from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import FoodAlias
from app.schemas.foods import AliasCreate, FoodCreate, FoodSearchResult, FoodUpdate
from app.services.food_service import (
    create_food,
    duplicate_food_to_custom,
    food_to_read,
    get_food,
    search_foods,
    update_food,
)
from app.services.parser import normalize_text


router = APIRouter(prefix="/api/foods", tags=["foods"])


@router.post("")
def create_food_endpoint(payload: FoodCreate, session: Session = Depends(get_session)) -> dict:
    food = create_food(session, payload)
    return {"food": food_to_read(session, food).model_dump()}


@router.put("/{food_id}")
def update_food_endpoint(
    food_id: int, payload: FoodUpdate, session: Session = Depends(get_session)
) -> dict:
    try:
        food = update_food(session, food_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"food": food_to_read(session, food).model_dump()}


@router.get("/search", response_model=FoodSearchResult)
def search_foods_endpoint(
    q: str | None = None,
    source: str | None = None,
    session: Session = Depends(get_session),
) -> FoodSearchResult:
    foods = [food_to_read(session, food) for food in search_foods(session, q, source)]
    return FoodSearchResult(foods=foods)


@router.post("/{food_id}/aliases")
def create_alias_endpoint(
    food_id: int, payload: AliasCreate, session: Session = Depends(get_session)
) -> dict:
    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    alias = FoodAlias(
        phrase=payload.phrase.strip(),
        normalized_phrase=normalize_text(payload.phrase),
        food_id=food_id,
    )
    session.add(alias)
    session.commit()
    return {"status": "ok"}


@router.post("/{food_id}/duplicate")
def duplicate_food_endpoint(food_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        food = duplicate_food_to_custom(session, food_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"food": food_to_read(session, food).model_dump()}

