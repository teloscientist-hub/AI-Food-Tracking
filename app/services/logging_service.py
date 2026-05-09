from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Food, FoodAlias, FoodResolutionHistory, MealEntry, MealEntryItem
from app.schemas.logging import LogMealRequest
from app.services.food_service import _source_payload_image_url, create_food
from app.services.parser import ParsedFoodItem, parse_entry, normalize_text
from app.services.resolution import FoodResolver, ResolutionResult
from app.schemas.foods import FoodCreate


def multiply_value(value: float | None, quantity: float) -> float | None:
    if value is None:
        return None
    return round(value * quantity, 2)


UNIT_TO_GRAMS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
    "tbsp": 14.0,
    "tsp": 4.67,
    "stick": 113.0,
    "sticks": 113.0,
    "cup": 240.0,
    "cups": 240.0,
}


def serving_multiplier(quantity: float, unit: str | None, food: Food) -> float:
    if not unit:
        return quantity
    normalized = unit.lower()
    if normalized in UNIT_TO_GRAMS and food.grams_per_serving and food.grams_per_serving > 0:
        grams = quantity * UNIT_TO_GRAMS[normalized]
        return grams / food.grams_per_serving
    return quantity


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
            image_url=candidate.get("image_url") or _source_payload_image_url(candidate.get("raw_payload")),
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

    def save_external_candidate_as_custom(
        self,
        session: Session,
        result_index: int,
        candidates: list[dict],
        alias_phrase: str | None = None,
    ) -> Food:
        candidate = candidates[result_index]
        aliases: list[str] = []
        if alias_phrase and normalize_text(alias_phrase) != normalize_text(candidate["canonical_name"]):
            aliases.append(alias_phrase)
        payload = FoodCreate(
            canonical_name=candidate["canonical_name"],
            brand=candidate.get("brand"),
            image_url=candidate.get("image_url") or _source_payload_image_url(candidate.get("raw_payload")),
            serving_description=candidate["serving_description"],
            grams_per_serving=float(candidate.get("grams_per_serving") or 1.0),
            calories=float(candidate.get("calories") or 0.0),
            protein_g=float(candidate.get("protein_g") or 0.0),
            carbs_g=float(candidate.get("carbs_g") or 0.0),
            fat_g=float(candidate.get("fat_g") or 0.0),
            fiber_g=candidate.get("fiber_g"),
            net_carbs_g=candidate.get("net_carbs_g"),
            aliases=aliases,
            notes=f"Saved to custom library from {candidate['source']}",
            authoritative_locked=False,
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
            if item.selected_food_id is None:
                session.add(
                    MealEntryItem(
                        meal_entry_id=meal_entry.id,
                        food_id=None,
                        parsed_phrase=item.parsed_phrase,
                        normalized_phrase=normalize_text(item.parsed_phrase),
                        quantity=item.quantity,
                        unit=item.unit,
                        quantity_text=item.quantity_text,
                        resolution_status="unresolved",
                        resolution_strategy="deferred",
                        resolution_confidence=0.0,
                        resolved_food_name=None,
                        resolved_source=None,
                        serving_description_snapshot=None,
                        grams_per_serving_snapshot=None,
                        calories_snapshot=0.0,
                        protein_g_snapshot=0.0,
                        carbs_g_snapshot=0.0,
                        fat_g_snapshot=0.0,
                        fiber_g_snapshot=None,
                        net_carbs_g_snapshot=None,
                    )
                )
                session.add(
                    FoodResolutionHistory(
                        phrase=item.parsed_phrase,
                        normalized_phrase=normalize_text(item.parsed_phrase),
                        food_id=None,
                        resolution_strategy="unresolved",
                        confidence=0.0,
                        action_taken="deferred",
                    )
                )
                continue

            food = session.get(Food, item.selected_food_id)
            if not food:
                raise ValueError(f"Food {item.selected_food_id} not found")
            multiplier = serving_multiplier(item.quantity, item.unit, food)

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
                grams_per_serving_snapshot=multiply_value(food.grams_per_serving, multiplier),
                calories_snapshot=multiply_value(food.calories, multiplier) or 0.0,
                protein_g_snapshot=multiply_value(food.protein_g, multiplier) or 0.0,
                carbs_g_snapshot=multiply_value(food.carbs_g, multiplier) or 0.0,
                fat_g_snapshot=multiply_value(food.fat_g, multiplier) or 0.0,
                fiber_g_snapshot=multiply_value(food.fiber_g, multiplier),
                net_carbs_g_snapshot=multiply_value(food.net_carbs_g, multiplier),
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
