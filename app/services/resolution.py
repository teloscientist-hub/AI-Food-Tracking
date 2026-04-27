from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import re
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


class BrandedFoodLookupClient(FoodLookupClient, Protocol):
    def search_branded(self, phrase: str, limit: int = 5) -> list[ExternalFoodCandidate]:
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


KNOWN_BRAND_MARKERS = {
    "kirkland",
    "ratio",
    "reese",
    "reese's",
    "one",
    "fairlife",
    "premier",
    "quest",
    "core",
    "power",
}

KNOWN_BRAND_PHRASES = {
    "pure protein",
    "premier protein",
    "kirkland signature",
    "dannon light fit",
}

PACKAGED_FOOD_MARKERS = {
    "bar",
    "yogurt",
    "shake",
    "protein",
    "cheddar",
    "shredded",
    "mix",
    "container",
    "bottle",
    "cup",
}


def normalized_tokens(phrase: str) -> set[str]:
    return set(normalize_text(phrase).split())


def source_rank(candidate: ResolutionCandidate) -> tuple[int, float]:
    if candidate.source == "openfoodfacts":
        return (0, -candidate.confidence)
    if candidate.strategy.startswith("usda_branded"):
        return (1, -candidate.confidence)
    if candidate.source == "usda":
        return (2, -candidate.confidence)
    return (3, -candidate.confidence)


def looks_branded(phrase: str) -> bool:
    normalized = normalize_text(phrase)
    tokens = normalized_tokens(phrase)
    if not tokens:
        return False
    if any(brand_phrase in normalized for brand_phrase in KNOWN_BRAND_PHRASES):
        return True
    if tokens & KNOWN_BRAND_MARKERS:
        return True
    packaged_hits = len(tokens & PACKAGED_FOOD_MARKERS)
    has_digits = any(char.isdigit() for char in phrase)
    return has_digits and packaged_hits > 0


def strongly_branded(phrase: str) -> bool:
    normalized = normalize_text(phrase)
    tokens = normalized_tokens(phrase)
    if any(brand_phrase in normalized for brand_phrase in KNOWN_BRAND_PHRASES):
        return True
    if tokens & KNOWN_BRAND_MARKERS:
        return True
    has_digits = any(char.isdigit() for char in phrase)
    return has_digits and len(tokens & PACKAGED_FOOD_MARKERS) >= 2


def prepare_search_phrase(phrase: str) -> str:
    cleaned = normalize_text(phrase)
    cleaned = re.sub(r"\bbrand\b", "", cleaned)
    cleaned = re.sub(r"\bwith \d+(?:\.\d+)? g of protein\b", "", cleaned)
    cleaned = re.sub(r"\bwith \d+(?:\.\d+)? grams? of protein\b", "", cleaned)
    cleaned = re.sub(r"\bof a\b", " ", cleaned)
    cleaned = re.sub(r"\bof\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_search_phrases(phrase: str) -> list[str]:
    base = prepare_search_phrase(phrase)
    variants = [base]
    variant_rules = [
        (r"\bprobiotic\b", ""),
        (r"\bshredded\b", ""),
        (r"\bmix\b", ""),
        (r"\bprotein bar\b", "bar"),
    ]
    for pattern, replacement in variant_rules:
        candidate = re.sub(pattern, replacement, base).strip()
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate and candidate not in variants:
            variants.append(candidate)
    if "ratio" in base and "yogurt" in base:
        ratio_variants = [
            re.sub(r"\b25 g\b", "", base).strip(),
            re.sub(r"\bprobiotic\b", "", re.sub(r"\b25 g\b", "", base)).strip(),
            "ratio protein yogurt blueberry",
            "ratio blueberry yogurt",
        ]
        for candidate in ratio_variants:
            candidate = re.sub(r"\s+", " ", candidate).strip()
            if candidate and candidate not in variants:
                variants.append(candidate)
    if "kirkland" in base and ("cheddar" in base or "jack" in base):
        kirkland_variants = [
            re.sub(r"\bshredded\b", "", base).strip(),
            re.sub(r"\bmix\b", "cheese", base).strip(),
            "kirkland cheddar jack cheese",
            "kirkland shredded cheddar jack cheese",
            re.sub(r"\band\b", "", re.sub(r"\bmix\b", "cheese", base)).strip(),
        ]
        for candidate in kirkland_variants:
            candidate = re.sub(r"\s+", " ", candidate).strip()
            if candidate and candidate not in variants:
                variants.append(candidate)
    if "reese" in base and "one" in base:
        candidate = "one reese's protein bar"
        if candidate not in variants:
            variants.append(candidate)
    return variants[:5]


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
        search_phrases = build_search_phrases(phrase)
        is_branded = looks_branded(search_phrases[0])
        is_strongly_branded = strongly_branded(search_phrases[0])
        branded_phrases = search_phrases if is_branded else search_phrases[:1]
        generic_phrases = search_phrases[:1]
        candidates: list[ResolutionCandidate] = []

        with ThreadPoolExecutor(max_workers=min(3, max(1, len(branded_phrases)))) as executor:
            future_map = {
                executor.submit(self.off_client.search, search_phrase): idx
                for idx, search_phrase in enumerate(branded_phrases)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                foods = future.result()
                candidates.extend(self._external_candidates(foods, "openfoodfacts_search", idx))

        if is_branded and hasattr(self.usda_client, "search_branded"):
            with ThreadPoolExecutor(max_workers=min(3, max(1, len(branded_phrases)))) as executor:
                future_map = {
                    executor.submit(self.usda_client.search_branded, search_phrase): idx  # type: ignore[attr-defined]
                    for idx, search_phrase in enumerate(branded_phrases)
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    foods = future.result()
                    candidates.extend(self._external_candidates(foods, "usda_branded_search", idx))

        branded_candidates = [
            candidate
            for candidate in candidates
            if candidate.strategy.startswith("usda_branded") or candidate.source == "openfoodfacts"
        ]
        top_branded = max(branded_candidates, key=lambda item: item.confidence, default=None)
        should_search_generic_usda = (
            not is_branded
            or top_branded is None
            or top_branded.confidence < 0.74
        )
        if should_search_generic_usda:
            with ThreadPoolExecutor(max_workers=min(2, len(generic_phrases))) as executor:
                future_map = {
                    executor.submit(self.usda_client.search, search_phrase): idx
                    for idx, search_phrase in enumerate(generic_phrases)
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    foods = future.result()
                    candidates.extend(self._external_candidates(foods, "usda_search", idx))

        adjusted: list[ResolutionCandidate] = []
        for candidate in candidates:
            bonus = 0.0
            penalty = 0.0
            has_brand = bool(candidate.brand and normalize_text(candidate.brand))
            if is_branded:
                if candidate.source == "openfoodfacts":
                    bonus += 0.08
                if candidate.strategy.startswith("usda_branded"):
                    bonus += 0.08
                elif candidate.source == "usda" and has_brand:
                    bonus += 0.04
                if candidate.source == "usda" and not has_brand:
                    penalty += 0.1
            if is_strongly_branded and candidate.source == "usda" and not has_brand:
                penalty += 0.08
            adjusted.append(
                replace(candidate, confidence=min(0.99, max(0.0, candidate.confidence + bonus - penalty)))
            )

        deduped: dict[tuple[str, str], ResolutionCandidate] = {}
        for candidate in adjusted:
            key = (candidate.source, normalize_text(candidate.canonical_name))
            existing = deduped.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                deduped[key] = candidate

        resolved = sorted(deduped.values(), key=source_rank)
        return resolved[:5]

    def _external_candidates(
        self, foods: list[ExternalFoodCandidate], strategy: str, search_index: int = 0
    ) -> list[ResolutionCandidate]:
        return [
            ResolutionCandidate(
                food_id=None,
                canonical_name=food.canonical_name,
                brand=food.brand,
                source=food.source,
                confidence=max(0.0, food.score - (search_index * 0.03)),
                strategy=strategy if search_index == 0 else f"{strategy}_variant",
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
