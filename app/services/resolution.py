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

WHOLE_FOOD_PROCESSED_MARKERS = {
    "dehydrated",
    "powder",
    "dried",
    "baked",
    "fried",
    "seasoned",
    "flavored",
    "flavour",
    "style",
    "chips",
}


def singularize_token(token: str) -> str:
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 3:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def is_simple_whole_food_query(phrase: str) -> bool:
    tokens = normalized_tokens(phrase)
    if not tokens:
        return False
    if looks_branded(phrase):
        return False
    if any(char.isdigit() for char in phrase):
        return False
    if tokens & PACKAGED_FOOD_MARKERS:
        return False
    return len(tokens) <= 3


def normalized_tokens(phrase: str) -> set[str]:
    return set(normalize_text(phrase).split())


def source_rank(candidate: ResolutionCandidate) -> tuple[int, float]:
    if candidate.source == "custom":
        custom_rank = 0 if candidate.strategy in {"exact_alias", "exact_custom_name"} else 1
        return (custom_rank, -candidate.confidence)
    if candidate.source == "openfoodfacts":
        return (2, -candidate.confidence)
    if candidate.strategy.startswith("usda_branded"):
        return (3, -candidate.confidence)
    if candidate.source == "usda":
        return (4, -candidate.confidence)
    return (5, -candidate.confidence)


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
        external_candidates = self._external_lookup(parsed_item.phrase)
        if fuzzy_matches or external_candidates:
            combined = sorted([*fuzzy_matches, *external_candidates], key=source_rank)
            top = combined[0]
            if top.source == "custom" and top.confidence >= 0.9:
                return ResolutionResult(parsed_item, "auto", top, combined[:8])
            if top.confidence >= 0.9:
                return ResolutionResult(parsed_item, "auto", top, combined[:8])
            if top.confidence >= 0.7:
                return ResolutionResult(parsed_item, "confirm", None, combined[:8])
            return ResolutionResult(parsed_item, "choose", None, combined[:8])

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
        foods = session.scalars(
            select(Food).where(Food.source == "custom", Food.is_current.is_(True))
        ).all()
        for food in foods:
            brand_name = normalize_text(f"{food.brand or ''} {food.canonical_name}")
            if food.normalized_name == normalized or brand_name == normalized:
                return self._food_candidate(food, 0.97, "exact_custom_name")
        return None

    def _fuzzy_custom_lookup(self, session: Session, normalized: str) -> list[ResolutionCandidate]:
        foods = session.scalars(
            select(Food).where(Food.source == "custom", Food.is_current.is_(True))
        ).all()
        aliases = session.scalars(select(FoodAlias).join(Food).where(Food.is_current.is_(True))).all()
        scored: list[ResolutionCandidate] = []
        seen_food_ids: set[int] = set()

        for food in foods:
            score = SequenceMatcher(None, normalized, food.normalized_name).ratio()
            brand_name = normalize_text(f"{food.brand or ''} {food.canonical_name}")
            brand_score = SequenceMatcher(None, normalized, brand_name).ratio()
            score = max(score, brand_score)
            query_tokens = set(normalized.split())
            brand_name_tokens = set(brand_name.split())
            brand_tokens = set(normalize_text(food.brand or "").split())
            overlap = len(query_tokens & brand_name_tokens)
            if overlap:
                score = max(score, min(0.92, 0.58 + (overlap * 0.08)))
                if query_tokens.issubset(brand_name_tokens):
                    score = max(score, 0.86)
            if brand_tokens and query_tokens & brand_tokens:
                score = max(score, 0.84)
                if brand_tokens.issubset(query_tokens):
                    score = max(score, 0.88)
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
        is_simple_whole_food = is_simple_whole_food_query(search_phrases[0])
        phrase_tokens = normalized_tokens(search_phrases[0])
        singular_tokens = {singularize_token(token) for token in phrase_tokens}
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
            raw_payload = candidate.raw_payload or {}
            data_type = normalize_text(str(raw_payload.get("dataType") or ""))
            candidate_name_tokens = normalized_tokens(candidate.canonical_name)
            candidate_singular_tokens = {singularize_token(token) for token in candidate_name_tokens}
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
            if is_simple_whole_food:
                if has_brand:
                    penalty += 0.35
                if "branded" in data_type:
                    penalty += 0.22
                if candidate.strategy.startswith("usda_branded"):
                    penalty += 0.12
                if candidate.source == "openfoodfacts":
                    penalty += 0.08
                processed_hits = len(candidate_singular_tokens & WHOLE_FOOD_PROCESSED_MARKERS)
                if processed_hits:
                    penalty += min(0.28, 0.18 + ((processed_hits - 1) * 0.05))
                overlap = len(singular_tokens & candidate_singular_tokens)
                if overlap:
                    bonus += min(0.12, overlap * 0.06)
                if candidate_singular_tokens == singular_tokens:
                    bonus += 0.12
                elif singular_tokens.issubset(candidate_singular_tokens):
                    bonus += 0.06
                if candidate.source == "usda" and not has_brand:
                    bonus += 0.06
                if "raw" in candidate_singular_tokens or "fresh" in candidate_singular_tokens:
                    bonus += 0.08
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
