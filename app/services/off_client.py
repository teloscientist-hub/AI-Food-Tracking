from __future__ import annotations

from difflib import SequenceMatcher
import re

import httpx

from app.config import get_settings
from app.services.parser import normalize_text
from app.services.usda_client import ExternalFoodCandidate


class OpenFoodFactsClient:
    base_url = "https://world.openfoodfacts.org/cgi/search.pl"

    def __init__(self) -> None:
        self.settings = get_settings()

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
            if match:
                return float(match.group(0))
        return None

    @classmethod
    def _grams_from_serving_size(cls, serving_size: object) -> float | None:
        if not serving_size:
            return None
        if isinstance(serving_size, (int, float)):
            return float(serving_size)
        if isinstance(serving_size, str):
            match = re.search(r"(\d+(?:[.,]\d+)?)\s*g\b", serving_size.lower())
            if match:
                return float(match.group(1).replace(",", "."))
        return None

    @classmethod
    def _read_nutrient(
        cls,
        nutriments: dict,
        base_key: str,
        grams_per_serving: float,
    ) -> float | None:
        direct_serving = cls._to_float(nutriments.get(f"{base_key}_serving"))
        if direct_serving is not None:
            return direct_serving

        direct_value = cls._to_float(nutriments.get(base_key))
        if direct_value is not None:
            nutrition_basis = str(nutriments.get("nutrition_data_per") or "").lower()
            if nutrition_basis == "serving":
                return direct_value

        per_100g = cls._to_float(nutriments.get(f"{base_key}_100g"))
        if per_100g is not None:
            return per_100g * grams_per_serving / 100.0

        if direct_value is not None:
            return direct_value
        return None

    def search(self, phrase: str, limit: int = 5) -> list[ExternalFoodCandidate]:
        headers = {"User-Agent": self.settings.openfoodfacts_user_agent}
        params = {
            "search_terms": phrase,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": limit,
        }
        try:
            timeout = httpx.Timeout(connect=1.5, read=2.5, write=2.5, pool=1.5)
            with httpx.Client(timeout=timeout, headers=headers) as client:
                response = client.get(self.base_url, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []

        normalized_phrase = normalize_text(phrase)
        results: list[ExternalFoodCandidate] = []
        for item in payload.get("products", []):
            product_name = item.get("product_name") or item.get("product_name_en") or ""
            if not product_name:
                continue
            nutriments = item.get("nutriments", {})
            grams_per_serving = (
                self._to_float(nutriments.get("serving_quantity"))
                or self._grams_from_serving_size(item.get("serving_size"))
                or self._to_float(item.get("product_quantity"))
                or 100.0
            )
            calories = (
                self._read_nutrient(nutriments, "energy-kcal", grams_per_serving)
                or self._read_nutrient(nutriments, "energy", grams_per_serving)
                or 0.0
            )
            protein_g = self._read_nutrient(nutriments, "proteins", grams_per_serving) or 0.0
            carbs_g = self._read_nutrient(nutriments, "carbohydrates", grams_per_serving) or 0.0
            fat_g = self._read_nutrient(nutriments, "fat", grams_per_serving) or 0.0
            fiber_g = self._read_nutrient(nutriments, "fiber", grams_per_serving)
            net_carbs_g = None
            if fiber_g is not None:
                net_carbs_g = max(0.0, carbs_g - fiber_g)
            normalized_name = normalize_text(product_name)
            normalized_brand = normalize_text(item.get("brands") or "")
            score = 0.48 + (SequenceMatcher(None, normalized_phrase, normalized_name).ratio() * 0.32)
            if normalized_name == normalized_phrase:
                score = 0.94
            elif normalized_phrase in normalized_name:
                score = 0.84
            phrase_tokens = set(normalized_phrase.split())
            name_tokens = set(normalized_name.split())
            brand_tokens = set(normalized_brand.split())
            overlap = len(phrase_tokens & name_tokens)
            if overlap:
                score += min(0.12, overlap * 0.03)
            if phrase_tokens & brand_tokens:
                score += 0.12
            results.append(
                ExternalFoodCandidate(
                    canonical_name=product_name,
                    brand=item.get("brands"),
                    source="openfoodfacts",
                    source_food_id=str(item.get("code") or product_name),
                    serving_description=item.get("serving_size") or "1 serving",
                    grams_per_serving=grams_per_serving,
                    calories=calories,
                    protein_g=protein_g,
                    carbs_g=carbs_g,
                    fat_g=fat_g,
                    fiber_g=fiber_g,
                    net_carbs_g=net_carbs_g,
                    raw_source_payload=item,
                    score=min(0.99, score),
                )
            )
        return results
