from __future__ import annotations

import httpx

from app.services.off_client import OpenFoodFactsClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        self.payload = payload

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        return _FakeResponse(self.payload)


def test_openfoodfacts_uses_plain_nutriment_keys_for_serving_payload(monkeypatch) -> None:
    payload = {
        "products": [
            {
                "product_name": "CAFE LATTE (premier protein)",
                "brands": "Premier Protein",
                "code": "12345",
                "serving_size": "1 serving (311.844 g)",
                "nutriments": {
                    "nutrition_data_per": "serving",
                    "energy-kcal": "160",
                    "proteins": "30",
                    "carbohydrates": "5",
                    "fat": "3",
                    "fiber": "1",
                },
            }
        ]
    }

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _FakeClient(payload))

    results = OpenFoodFactsClient().search("premier protein cafe latte")

    assert len(results) == 1
    result = results[0]
    assert result.calories == 160.0
    assert result.protein_g == 30.0
    assert result.carbs_g == 5.0
    assert result.fat_g == 3.0
    assert result.fiber_g == 1.0
    assert result.net_carbs_g == 4.0
    assert result.grams_per_serving == 311.844


def test_openfoodfacts_scales_100g_nutrients_to_serving_size(monkeypatch) -> None:
    payload = {
        "products": [
            {
                "product_name": "Ratio Protein Yogurt Blueberry",
                "brands": "Ratio",
                "code": "67890",
                "serving_size": "150 g",
                "nutriments": {
                    "energy-kcal_100g": "100",
                    "proteins_100g": "10",
                    "carbohydrates_100g": "8",
                    "fat_100g": "3",
                    "fiber_100g": "2",
                },
            }
        ]
    }

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _FakeClient(payload))

    results = OpenFoodFactsClient().search("ratio blueberry yogurt")

    assert len(results) == 1
    result = results[0]
    assert result.calories == 150.0
    assert result.protein_g == 15.0
    assert result.carbs_g == 12.0
    assert result.fat_g == 4.5
    assert result.fiber_g == 3.0
    assert result.net_carbs_g == 9.0
    assert result.grams_per_serving == 150.0
