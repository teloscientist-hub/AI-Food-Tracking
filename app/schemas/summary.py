from __future__ import annotations

from pydantic import BaseModel


class MacroValue(BaseModel):
    consumed: float
    remaining: float
    target: float | None


class DailySummaryRead(BaseModel):
    date: str
    calories: MacroValue
    protein: MacroValue
    carbs: MacroValue
    fat: MacroValue
    fiber: MacroValue | None
    net_carbs: MacroValue | None
    streak_days: int
    last_logged_at: str | None
    status_text: str


class WeeklyDaySummary(BaseModel):
    day: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    net_carbs_g: float


class WeeklySummaryRead(BaseModel):
    metric: str
    days: list[WeeklyDaySummary]
    averages: dict[str, float]
    top_foods: list[dict[str, float | str]]
    adherence_days: int

