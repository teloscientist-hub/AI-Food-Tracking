from __future__ import annotations

import httpx

from app.config import get_settings
from app.services.parser import normalize_text
from app.services.usda_client import ExternalFoodCandidate


class OpenFoodFactsClient:
    base_url = "https://world.openfoodfacts.org/cgi/search.pl"

    def __init__(self) -> None:
        self.settings = get_settings()

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
            with httpx.Client(timeout=8.0, headers=headers) as client:
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
            score = 0.5
            if normalize_text(product_name) == normalized_phrase:
                score = 0.94
            elif normalized_phrase in normalize_text(product_name):
                score = 0.8
            results.append(
                ExternalFoodCandidate(
                    canonical_name=product_name,
                    brand=item.get("brands"),
                    source="openfoodfacts",
                    source_food_id=str(item.get("code") or product_name),
                    serving_description=item.get("serving_size") or "1 serving",
                    grams_per_serving=float(
                        nutriments.get("serving_quantity")
                        or item.get("product_quantity")
                        or 100.0
                    ),
                    calories=float(
                        nutriments.get("energy-kcal_serving")
                        or nutriments.get("energy-kcal_100g")
                        or 0.0
                    ),
                    protein_g=float(
                        nutriments.get("proteins_serving")
                        or nutriments.get("proteins_100g")
                        or 0.0
                    ),
                    carbs_g=float(
                        nutriments.get("carbohydrates_serving")
                        or nutriments.get("carbohydrates_100g")
                        or 0.0
                    ),
                    fat_g=float(
                        nutriments.get("fat_serving") or nutriments.get("fat_100g") or 0.0
                    ),
                    fiber_g=float(
                        nutriments.get("fiber_serving")
                        or nutriments.get("fiber_100g")
                        or 0.0
                    )
                    if nutriments.get("fiber_serving") is not None
                    or nutriments.get("fiber_100g") is not None
                    else None,
                    net_carbs_g=None,
                    raw_source_payload=item,
                    score=score,
                )
            )
        return results

