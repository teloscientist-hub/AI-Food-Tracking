from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.services.parser import normalize_text


@dataclass(slots=True)
class ExternalFoodCandidate:
    canonical_name: str
    brand: str | None
    source: str
    source_food_id: str
    serving_description: str
    grams_per_serving: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    net_carbs_g: float | None
    raw_source_payload: dict
    score: float


class USDAClient:
    base_url = "https://api.nal.usda.gov/fdc/v1/foods/search"

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_enabled(self) -> bool:
        return bool(self.settings.usda_api_key)

    def search(self, phrase: str, limit: int = 5) -> list[ExternalFoodCandidate]:
        if not self.is_enabled():
            return []
        params = {
            "api_key": self.settings.usda_api_key,
            "query": phrase,
            "pageSize": limit,
        }
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(self.base_url, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []

        results: list[ExternalFoodCandidate] = []
        normalized_phrase = normalize_text(phrase)
        for item in payload.get("foods", []):
            nutrients = {n.get("nutrientName"): n.get("value") for n in item.get("foodNutrients", [])}
            name = item.get("description") or "USDA Food"
            brand = item.get("brandOwner")
            score = 0.55
            if normalize_text(name) == normalized_phrase:
                score = 0.96
            elif normalized_phrase in normalize_text(name):
                score = 0.82
            results.append(
                ExternalFoodCandidate(
                    canonical_name=name.title(),
                    brand=brand,
                    source="usda",
                    source_food_id=str(item.get("fdcId")),
                    serving_description=item.get("servingSizeUnit") or "1 serving",
                    grams_per_serving=float(item.get("servingSize") or 100.0),
                    calories=float(nutrients.get("Energy") or 0.0),
                    protein_g=float(nutrients.get("Protein") or 0.0),
                    carbs_g=float(nutrients.get("Carbohydrate, by difference") or 0.0),
                    fat_g=float(nutrients.get("Total lipid (fat)") or 0.0),
                    fiber_g=float(nutrients.get("Fiber, total dietary") or 0.0)
                    if nutrients.get("Fiber, total dietary") is not None
                    else None,
                    net_carbs_g=None,
                    raw_source_payload=item,
                    score=score,
                )
            )
        return results

