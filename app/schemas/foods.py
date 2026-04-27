from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FoodBase(BaseModel):
    canonical_name: str
    brand: str | None = None
    serving_description: str = "1 serving"
    grams_per_serving: float = 1.0
    calories: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float | None = None
    net_carbs_g: float | None = None
    aliases: list[str] = Field(default_factory=list)


class FoodCreate(FoodBase):
    notes: str | None = None
    authoritative_locked: bool = False
    source: str = "custom"
    source_food_id: str | None = None
    raw_source_payload: dict | None = None


class FoodUpdate(FoodBase):
    notes: str | None = None
    authoritative_locked: bool = False


class FoodRead(FoodBase):
    id: int
    source: str
    source_food_id: str | None = None
    image_url: str | None = None
    version: int
    is_current: bool
    food_group_key: str | None = None
    created_at: datetime
    updated_at: datetime
    notes: str | None = None
    authoritative_locked: bool = False

    model_config = {"from_attributes": True}


class FoodSearchResult(BaseModel):
    foods: list[FoodRead]


class AliasCreate(BaseModel):
    phrase: str
