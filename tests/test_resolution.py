from app.schemas.foods import FoodCreate
from app.services.food_service import create_food
from app.services.parser import parse_food_phrase
from app.services.resolution import FoodResolver
from app.services.usda_client import ExternalFoodCandidate


class FakeClient:
    def __init__(self, results):
        self._results = results

    def search(self, phrase: str, limit: int = 5):
        return list(self._results)


def test_resolution_prefers_exact_custom_alias(session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="Fairlife Core Power Elite 42g",
            brand="Fairlife",
            serving_description="1 bottle",
            grams_per_serving=414,
            calories=230,
            protein_g=42,
            carbs_g=9,
            fat_g=3.5,
            aliases=["Fairlife 42"],
            authoritative_locked=True,
        ),
    )
    resolver = FoodResolver(
        usda_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Generic Protein Shake",
                    brand=None,
                    source="usda",
                    source_food_id="123",
                    serving_description="1 serving",
                    grams_per_serving=100,
                    calories=150,
                    protein_g=20,
                    carbs_g=10,
                    fat_g=2,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.99,
                )
            ]
        ),
        off_client=FakeClient([]),
    )

    result = resolver.resolve(session, parse_food_phrase("1 Fairlife 42"))

    assert result.status == "auto"
    assert result.chosen is not None
    assert result.chosen.source == "custom"
    assert result.chosen.strategy == "exact_alias"


def test_resolution_falls_back_to_external_when_custom_misses(session) -> None:
    resolver = FoodResolver(
        usda_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Chicken Breast",
                    brand=None,
                    source="usda",
                    source_food_id="456",
                    serving_description="1 serving",
                    grams_per_serving=100,
                    calories=165,
                    protein_g=31,
                    carbs_g=0,
                    fat_g=3.6,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.92,
                )
            ]
        ),
        off_client=FakeClient([]),
    )

    result = resolver.resolve(session, parse_food_phrase("1 chicken breast"))

    assert result.status == "auto"
    assert result.chosen is not None
    assert result.chosen.source == "usda"

