from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Protocol

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models import CustomFoodMetadata, Food, FoodAlias
from app.services.parser import ParsedFoodItem, normalize_text
from app.services.usda_client import ExternalFoodCandidate, USDAClient
from app.services.off_client import OpenFoodFactsClient


class FoodLookupClient(Protocol):
    def search(self, phrase: str, limit: int = 5) -> list[ExternalFoodCandidate]:
        ...


@dataclass(slots=True)
class ResolutionCandidate:
    food_id: int | None
    canonical_name: str
    brand: str | None
    source: str
    confidence: float
    strategy: str
    serving_description: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    net_carbs_g: float | None
    raw_payload: dict | None = None


@dataclass(slots=True)
class ResolutionResult:
    parsed_item: ParsedFoodItem
    status: str
    chosen: ResolutionCandidate | None
    candidates: list[ResolutionCandidate]


def looks_branded(phrase: str) -> bool:
    return any(char.isdigit() for char in phrase) or len(phrase.split()) >= 2


class FoodResolver:
    def __init__(
        self,
        usda_client: FoodLookupClient | None = None,
        off_client: FoodLookupClient | None = None,
    ) -> None:
        self.usda_client = usda_client or USDAClient()
        self.off_client = off_client or OpenFoodFactsClient()

    def resolve(self, session: Session, parsed_item: ParsedFoodItem) -> ResolutionResult:
        normalized = normalize_text(parsed_item.phrase)

        exact_alias = self._exact_alias_lookup(session, normalized)
        if exact_alias:
            return ResolutionResult(parsed_item, "auto", exact_alias, [exact_alias])

        exact_custom = self._exact_custom_lookup(session, normalized)
        if exact_custom:
            return ResolutionResult(parsed_item, "auto", exact_custom, [exact_custom])

        fuzzy_matches = self._fuzzy_custom_lookup(session, normalized)
        if fuzzy_matches:
            chosen = fuzzy_matches[0] if fuzzy_matches[0].confidence >= 0.9 else None
            status = "auto" if chosen else "confirm"
            return ResolutionResult(parsed_item, status, chosen, fuzzy_matches)

        external_candidates = self._external_lookup(parsed_item.phrase)
        if external_candidates:
            top = external_candidates[0]
            if top.confidence >= 0.9:
                return ResolutionResult(parsed_item, "auto", top, external_candidates)
            if top.confidence >= 0.7:
                return ResolutionResult(parsed_item, "confirm", None, external_candidates)
            return ResolutionResult(parsed_item, "choose", None, external_candidates)

        return ResolutionResult(parsed_item, "unresolved", None, [])

    def _exact_alias_lookup(self, session: Session, normalized: str) -> ResolutionCandidate | None:
        stmt = (
            select(FoodAlias, Food, CustomFoodMetadata)
            .join(Food, FoodAlias.food_id == Food.id)
            .outerjoin(CustomFoodMetadata, CustomFoodMetadata.food_group_key == Food.food_group_key)
            .where(FoodAlias.normalized_phrase == normalized, Food.is_current.is_(True))
            .order_by(
                case((Food.source == "custom", 0), else_=1),
                case((CustomFoodMetadata.authoritative_locked.is_(True), 0), else_=1),
            )
        )
        row = session.execute(stmt).first()
        if not row:
            return None
        _, food, _ = row
        return self._food_candidate(food, 0.99, "exact_alias")

    def _exact_custom_lookup(self, session: Session, normalized: str) -> ResolutionCandidate | None:
        food = session.scalar(
            select(Food)
            .where(
                Food.source == "custom",
                Food.is_current.is_(True),
                Food.normalized_name == normalized,
            )
            .limit(1)
        )
        if not food:
            return None
        return self._food_candidate(food, 0.97, "exact_custom_name")

    def _fuzzy_custom_lookup(self, session: Session, normalized: str) -> list[ResolutionCandidate]:
        foods = session.scalars(
            select(Food).where(Food.source == "custom", Food.is_current.is_(True))
        ).all()
        aliases = session.scalars(select(FoodAlias).join(Food).where(Food.is_current.is_(True))).all()
        scored: list[ResolutionCandidate] = []
        seen_food_ids: set[int] = set()

        for food in foods:
            score = SequenceMatcher(None, normalized, food.normalized_name).ratio()
            if score >= 0.72 and food.id not in seen_food_ids:
                scored.append(self._food_candidate(food, score, "fuzzy_custom_name"))
                seen_food_ids.add(food.id)
        for alias in aliases:
            score = SequenceMatcher(None, normalized, alias.normalized_phrase).ratio()
            if score >= 0.72 and alias.food_id not in seen_food_ids:
                food = alias.food
                scored.append(self._food_candidate(food, score, "fuzzy_custom_alias"))
                seen_food_ids.add(alias.food_id)

        scored.sort(key=lambda item: item.confidence, reverse=True)
        return scored[:5]

    def _external_lookup(self, phrase: str) -> list[ResolutionCandidate]:
        candidates: list[ResolutionCandidate] = []
        usda = self.usda_client.search(phrase)
        candidates.extend(self._external_candidates(usda, "usda_search"))

        top_usda = candidates[0] if candidates else None
        should_use_off = top_usda is None or top_usda.confidence < 0.78 or looks_branded(phrase)
        if should_use_off:
            off = self.off_client.search(phrase)
            candidates.extend(self._external_candidates(off, "openfoodfacts_search"))

        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[:5]

    def _external_candidates(
        self, foods: list[ExternalFoodCandidate], strategy: str
    ) -> list[ResolutionCandidate]:
        return [
            ResolutionCandidate(
                food_id=None,
                canonical_name=food.canonical_name,
                brand=food.brand,
                source=food.source,
                confidence=food.score,
                strategy=strategy,
                serving_description=food.serving_description,
                calories=food.calories,
                protein_g=food.protein_g,
                carbs_g=food.carbs_g,
                fat_g=food.fat_g,
                fiber_g=food.fiber_g,
                net_carbs_g=food.net_carbs_g,
                raw_payload=asdict(food),
            )
            for food in foods
        ]

    @staticmethod
    def _food_candidate(food: Food, confidence: float, strategy: str) -> ResolutionCandidate:
        return ResolutionCandidate(
            food_id=food.id,
            canonical_name=food.canonical_name,
            brand=food.brand,
            source=food.source,
            confidence=confidence,
            strategy=strategy,
            serving_description=food.serving_description,
            calories=food.calories,
            protein_g=food.protein_g,
            carbs_g=food.carbs_g,
            fat_g=food.fat_g,
            fiber_g=food.fiber_g,
            net_carbs_g=food.net_carbs_g,
        )
