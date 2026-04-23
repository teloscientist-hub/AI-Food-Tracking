from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LogReviewItem(BaseModel):
    parsed_phrase: str
    quantity: float = 1.0
    unit: str | None = None
    quantity_text: str | None = None
    selected_food_id: int
    always_map: bool = False


class LogMealRequest(BaseModel):
    raw_input_text: str
    meal_label: str = "General"
    logged_at: datetime | None = None
    items: list[LogReviewItem] = Field(default_factory=list)

