from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Food(Base):
    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_food_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    serving_description: Mapped[str] = mapped_column(String(255), default="1 serving")
    grams_per_serving: Mapped[float] = mapped_column(Float, default=1.0)
    calories: Mapped[float] = mapped_column(Float, default=0.0)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_source_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    food_group_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    aliases: Mapped[list["FoodAlias"]] = relationship("FoodAlias", back_populates="food")


class FoodAlias(Base):
    __tablename__ = "food_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phrase: Mapped[str] = mapped_column(String(255))
    normalized_phrase: Mapped[str] = mapped_column(String(255), index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    food: Mapped["Food"] = relationship("Food", back_populates="aliases")


class CustomFoodMetadata(Base):
    __tablename__ = "custom_food_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_group_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    current_food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    authoritative_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


class MealEntry(Base):
    __tablename__ = "meal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_input_text: Mapped[str] = mapped_column(Text)
    meal_label: Mapped[str] = mapped_column(String(100), default="General")
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    items: Mapped[list["MealEntryItem"]] = relationship(
        "MealEntryItem", back_populates="meal_entry", cascade="all, delete-orphan"
    )


class MealEntryItem(Base):
    __tablename__ = "meal_entry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meal_entry_id: Mapped[int] = mapped_column(ForeignKey("meal_entries.id"), index=True)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"), nullable=True, index=True)
    parsed_phrase: Mapped[str] = mapped_column(String(255))
    normalized_phrase: Mapped[str] = mapped_column(String(255), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(50), default="resolved")
    resolution_strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_food_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    serving_description_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grams_per_serving_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    protein_g_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    carbs_g_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    fiber_g_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_carbs_g_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    meal_entry: Mapped["MealEntry"] = relationship("MealEntry", back_populates="items")


class DailyTarget(Base):
    __tablename__ = "daily_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    calories_target: Mapped[float] = mapped_column(Float, default=2000.0)
    protein_target_g: Mapped[float] = mapped_column(Float, default=180.0)
    carbs_target_g: Mapped[float] = mapped_column(Float, default=120.0)
    fat_target_g: Mapped[float] = mapped_column(Float, default=70.0)
    fiber_target_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_carbs_target_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class DailyNote(Base):
    __tablename__ = "daily_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class FoodResolutionHistory(Base):
    __tablename__ = "food_resolution_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phrase: Mapped[str] = mapped_column(String(255))
    normalized_phrase: Mapped[str] = mapped_column(String(255), index=True)
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"), nullable=True)
    resolution_strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_taken: Mapped[str] = mapped_column(String(50), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
