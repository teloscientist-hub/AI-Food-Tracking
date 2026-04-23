from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Food, FoodAlias, FoodResolutionHistory, MealEntry, MealEntryItem
from app.schemas.logging import LogMealRequest
from app.services.food_service import create_food
from app.services.parser import ParsedFoodItem, parse_entry, normalize_text
from app.services.resolution import FoodResolver, ResolutionResult
from app.schemas.foods import FoodCreate


def multiply_value(value: float | None, quantity: float) -> float | None:
    if value is None:
        return None
    return round(value * quantity, 2)


class LoggingService:
    def __init__(self, resolver: FoodResolver | None = None) -> None:
        self.resolver = resolver or FoodResolver()

    def build_review(self, session: Session, raw_text: str) -> list[ResolutionResult]:
        parsed = parse_entry(raw_text)
        return [self.resolver.resolve(session, item) for item in parsed]

    def persist_external_candidate(self, session: Session, result_index: int, candidates: list[dict]) -> Food:
        candidate = candidates[result_index]
        payload = FoodCreate(
            canonical_name=candidate["canonical_name"],
            brand=candidate.get("brand"),
            serving_description=candidate["serving_description"],
            grams_per_serving=float(candidate.get("grams_per_serving") or 1.0),
            calories=float(candidate.get("calories") or 0.0),
            protein_g=float(candidate.get("protein_g") or 0.0),
            carbs_g=float(candidate.get("carbs_g") or 0.0),
            fat_g=float(candidate.get("fat_g") or 0.0),
            fiber_g=candidate.get("fiber_g"),
            net_carbs_g=candidate.get("net_carbs_g"),
            aliases=[],
            notes=f"Imported from {candidate['source']}",
            authoritative_locked=False,
            source=candidate["source"],
            source_food_id=str(candidate.get("source_food_id") or candidate["canonical_name"]),
            raw_source_payload=candidate.get("raw_payload"),
        )
        return create_food(session, payload)

    def save_meal(self, session: Session, request: LogMealRequest) -> MealEntry:
        meal_entry = MealEntry(
            raw_input_text=request.raw_input_text,
            meal_label=request.meal_label,
            logged_at=request.logged_at or datetime.now(UTC),
        )
        session.add(meal_entry)
        session.flush()

        for item in request.items:
            food = session.get(Food, item.selected_food_id)
            if not food:
                raise ValueError(f"Food {item.selected_food_id} not found")

            meal_item = MealEntryItem(
                meal_entry_id=meal_entry.id,
                food_id=food.id,
                parsed_phrase=item.parsed_phrase,
                normalized_phrase=normalize_text(item.parsed_phrase),
                quantity=item.quantity,
                unit=item.unit,
                quantity_text=item.quantity_text,
                resolution_status="resolved",
                resolution_strategy="confirmed" if item.always_map else "logged",
                resolution_confidence=1.0,
                resolved_food_name=food.canonical_name,
                resolved_source=food.source,
                serving_description_snapshot=food.serving_description,
                grams_per_serving_snapshot=multiply_value(food.grams_per_serving, item.quantity),
                calories_snapshot=multiply_value(food.calories, item.quantity) or 0.0,
                protein_g_snapshot=multiply_value(food.protein_g, item.quantity) or 0.0,
                carbs_g_snapshot=multiply_value(food.carbs_g, item.quantity) or 0.0,
                fat_g_snapshot=multiply_value(food.fat_g, item.quantity) or 0.0,
                fiber_g_snapshot=multiply_value(food.fiber_g, item.quantity),
                net_carbs_g_snapshot=multiply_value(food.net_carbs_g, item.quantity),
            )
            session.add(meal_item)
            session.add(
                FoodResolutionHistory(
                    phrase=item.parsed_phrase,
                    normalized_phrase=normalize_text(item.parsed_phrase),
                    food_id=food.id,
                    resolution_strategy="always_map" if item.always_map else "logged",
                    confidence=1.0,
                    action_taken="confirm" if item.always_map else "auto",
                )
            )
            if item.always_map:
                existing_alias = session.query(FoodAlias).filter_by(
                    normalized_phrase=normalize_text(item.parsed_phrase), food_id=food.id
                ).first()
                if not existing_alias:
                    session.add(
                        FoodAlias(
                            phrase=item.parsed_phrase,
                            normalized_phrase=normalize_text(item.parsed_phrase),
                            food_id=food.id,
                        )
                    )

        session.commit()
        session.refresh(meal_entry)
        return meal_entry
