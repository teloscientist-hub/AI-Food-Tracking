from app.schemas.foods import FoodCreate
from app.services.food_service import create_food
from app.services.parser import parse_food_phrase
from app.services.resolution import FoodResolver, build_search_phrases, is_simple_whole_food_query, looks_branded, prepare_search_phrase, strongly_branded
from app.services.usda_client import ExternalFoodCandidate


class FakeClient:
    def __init__(self, results, branded_results=None):
        self._results = results
        self._branded_results = branded_results if branded_results is not None else []

    def search(self, phrase: str, limit: int = 5):
        return list(self._results)

    def search_branded(self, phrase: str, limit: int = 5):
        return list(self._branded_results)


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


def test_prepare_search_phrase_strips_brand_filler() -> None:
    assert (
        prepare_search_phrase('1 Reese\'s brand protein bar "One" with 18 g of protein')
        == "1 reese s protein bar one"
    )


def test_build_search_phrases_adds_branded_variants() -> None:
    ratio_variants = build_search_phrases("ratio 25 g blueberry probiotic yogurt")
    assert "ratio protein yogurt blueberry" in ratio_variants
    assert "ratio blueberry yogurt" in ratio_variants

    kirkland_variants = build_search_phrases("Kirkland shredded cheddar and jack mix")
    assert "kirkland cheddar jack cheese" in kirkland_variants
    assert "kirkland shredded cheddar and jack cheese" in kirkland_variants


def test_branded_phrase_detection_requires_real_brand_signal() -> None:
    assert looks_branded("Ratio brand 25G blueberry probiotic yogurt") is True
    assert strongly_branded("Kirkland shredded cheddar") is True
    assert looks_branded("Pure Protein Cafe Latte") is True
    assert strongly_branded("Premier Protein Cafe Latte") is True
    assert is_simple_whole_food_query("avocado") is True
    assert looks_branded("five eggs") is False


def test_resolution_prefers_off_for_branded_results_when_usda_is_weak(session) -> None:
    resolver = FoodResolver(
        usda_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Formulated Bar, South Beach Protein Bar",
                    brand=None,
                    source="usda",
                    source_food_id="111",
                    serving_description="1 bar",
                    grams_per_serving=60,
                    calories=200,
                    protein_g=18,
                    carbs_g=20,
                    fat_g=7,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.55,
                )
            ]
        ),
        off_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="One Protein Bar Reese's",
                    brand="ONE",
                    source="openfoodfacts",
                    source_food_id="222",
                    serving_description="1 bar",
                    grams_per_serving=60,
                    calories=220,
                    protein_g=18,
                    carbs_g=22,
                    fat_g=8,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.82,
                )
            ]
        ),
    )

    result = resolver.resolve(session, parse_food_phrase('1 Reese\'s brand protein bar "One" with 18 g of protein'))

    assert result.candidates[0].source == "openfoodfacts"


def test_resolution_penalizes_generic_usda_for_strong_brand_queries(session) -> None:
    resolver = FoodResolver(
        usda_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Cheese, Cheddar",
                    brand=None,
                    source="usda",
                    source_food_id="333",
                    serving_description="1 oz",
                    grams_per_serving=28,
                    calories=110,
                    protein_g=7,
                    carbs_g=1,
                    fat_g=9,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.86,
                )
            ]
        ),
        off_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Kirkland Signature Mexican Style Blend Cheese",
                    brand="Kirkland Signature",
                    source="openfoodfacts",
                    source_food_id="444",
                    serving_description="28 g",
                    grams_per_serving=28,
                    calories=110,
                    protein_g=7,
                    carbs_g=1,
                    fat_g=9,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.79,
                )
            ]
        ),
    )

    result = resolver.resolve(session, parse_food_phrase("1.5 oz Kirkland shredded cheddar"))

    assert result.candidates[0].source == "openfoodfacts"


def test_resolution_prefers_openfoodfacts_before_usda_branded_for_brand_query(session) -> None:
    class SplitUSDAClient:
        def search(self, phrase: str, limit: int = 5):
            return [
                ExternalFoodCandidate(
                    canonical_name="Cheese, Cheddar",
                    brand=None,
                    source="usda",
                    source_food_id="555",
                    serving_description="1 oz",
                    grams_per_serving=28,
                    calories=115,
                    protein_g=7,
                    carbs_g=1,
                    fat_g=9,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.86,
                )
            ]

        def search_branded(self, phrase: str, limit: int = 5):
            return [
                ExternalFoodCandidate(
                    canonical_name="Kirkland Signature Shredded Cheddar Jack Cheese",
                    brand="Kirkland Signature",
                    source="usda",
                    source_food_id="556",
                    serving_description="1 oz",
                    grams_per_serving=28,
                    calories=110,
                    protein_g=7,
                    carbs_g=1,
                    fat_g=9,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.8,
                )
            ]

    resolver = FoodResolver(
        usda_client=SplitUSDAClient(),
        off_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Kirkland Signature Shredded Cheddar Jack Cheese",
                    brand="Kirkland Signature",
                    source="openfoodfacts",
                    source_food_id="557",
                    serving_description="1 oz",
                    grams_per_serving=28,
                    calories=110,
                    protein_g=7,
                    carbs_g=1,
                    fat_g=9,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.79,
                )
            ]
        ),
    )

    result = resolver.resolve(session, parse_food_phrase("1.5 oz Kirkland shredded cheddar and jack mix"))

    assert result.candidates[0].source == "openfoodfacts"
    assert result.candidates[1].strategy.startswith("usda_branded")


def test_resolution_prefers_generic_whole_food_over_branded_product_for_simple_query(session) -> None:
    class SplitClient:
        def search(self, phrase: str, limit: int = 5):
            return [
                ExternalFoodCandidate(
                    canonical_name="Evolution Fresh, Organic Avocado Greens, Avacado, Avacado",
                    brand="Evolution Fresh",
                    source="usda",
                    source_food_id="901",
                    serving_description="1 bottle",
                    grams_per_serving=325,
                    calories=46,
                    protein_g=1.25,
                    carbs_g=6.67,
                    fat_g=1.67,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.88,
                ),
                ExternalFoodCandidate(
                    canonical_name="Avocados, Raw, All Commercial Varieties",
                    brand=None,
                    source="usda",
                    source_food_id="902",
                    serving_description="1 avocado",
                    grams_per_serving=150,
                    calories=240,
                    protein_g=3,
                    carbs_g=12.8,
                    fat_g=22,
                    fiber_g=10,
                    net_carbs_g=2.8,
                    raw_source_payload={},
                    score=0.82,
                ),
            ]

        def search_branded(self, phrase: str, limit: int = 5):
            return []

    resolver = FoodResolver(usda_client=SplitClient(), off_client=FakeClient([]))

    result = resolver.resolve(session, parse_food_phrase("1 avocado"))

    assert result.candidates[0].canonical_name == "Avocados, Raw, All Commercial Varieties"
    assert result.candidates[0].source == "usda"


def test_resolution_skips_generic_usda_when_branded_sources_are_strong(session) -> None:
    class SplitClient:
        def search(self, phrase: str, limit: int = 5):
            return [
                ExternalFoodCandidate(
                    canonical_name="Yogurt, blueberry",
                    brand=None,
                    source="usda",
                    source_food_id="777",
                    serving_description="1 container",
                    grams_per_serving=150,
                    calories=180,
                    protein_g=6,
                    carbs_g=24,
                    fat_g=4,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.92,
                )
            ]

        def search_branded(self, phrase: str, limit: int = 5):
            return [
                ExternalFoodCandidate(
                    canonical_name="Ratio Protein Yogurt Blueberry",
                    brand="Ratio",
                    source="usda",
                    source_food_id="778",
                    serving_description="1 container",
                    grams_per_serving=150,
                    calories=170,
                    protein_g=25,
                    carbs_g=8,
                    fat_g=4,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.8,
                )
            ]

    resolver = FoodResolver(
        usda_client=SplitClient(),
        off_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Ratio Protein Yogurt Blueberry",
                    brand="Ratio",
                    source="openfoodfacts",
                    source_food_id="779",
                    serving_description="1 container",
                    grams_per_serving=150,
                    calories=170,
                    protein_g=25,
                    carbs_g=8,
                    fat_g=4,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.78,
                )
            ]
        ),
    )

    result = resolver.resolve(session, parse_food_phrase("1 ratio 25 g blueberry probiotic yogurt"))

    assert result.candidates[0].source == "openfoodfacts"
    assert result.candidates[1].strategy.startswith("usda_branded")


def test_resolution_queries_openfoodfacts_before_usda_for_brand_query(session) -> None:
    call_order: list[tuple[str, str]] = []

    class RecordingUSDAClient:
        def search(self, phrase: str, limit: int = 5):
            call_order.append(("usda_generic", phrase))
            return []

        def search_branded(self, phrase: str, limit: int = 5):
            call_order.append(("usda_branded", phrase))
            return []

    class RecordingOFFClient:
        def search(self, phrase: str, limit: int = 5):
            call_order.append(("openfoodfacts", phrase))
            return []

    resolver = FoodResolver(
        usda_client=RecordingUSDAClient(),
        off_client=RecordingOFFClient(),
    )

    resolver.resolve(session, parse_food_phrase("1 Reese's brand protein bar \"One\" with 18 g of protein"))

    assert call_order
    assert call_order[0][0] == "openfoodfacts"


def test_resolution_prefers_brand_plus_name_custom_match(session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="Buffalo Style Crispy Protein Chips",
            brand="Wilde",
            serving_description="20 chips",
            grams_per_serving=1,
            calories=43,
            protein_g=3,
            carbs_g=2,
            fat_g=3,
            aliases=[],
        ),
    )

    resolver = FoodResolver(
        usda_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Protein Chips",
                    brand=None,
                    source="usda",
                    source_food_id="usda-1",
                    serving_description="1 serving",
                    grams_per_serving=28,
                    calories=140,
                    protein_g=10,
                    carbs_g=12,
                    fat_g=3,
                    fiber_g=None,
                    net_carbs_g=None,
                    raw_source_payload={},
                    score=0.76,
                )
            ]
        ),
        off_client=FakeClient(
            [
                ExternalFoodCandidate(
                    canonical_name="Protein Chips Buffalo Style",
                    brand="Wilde",
                    source="openfoodfacts",
                    source_food_id="off-1",
                    serving_description="20 chips",
                    grams_per_serving=28,
                    calories=43,
                    protein_g=3,
                    carbs_g=2,
                    fat_g=3,
                    fiber_g=None,
                    net_carbs_g=2,
                    raw_source_payload={},
                    score=0.8,
                )
            ]
        ),
    )

    result = resolver.resolve(session, parse_food_phrase("1 wilde protein chips"))

    assert result.candidates[0].source == "custom"
    assert "Wilde" in (result.candidates[0].brand or "")


def test_resolution_prefers_custom_for_wilde_brand_phrase(session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="Wilde Protein Chips Korean Sweet and Spicy",
            brand="Wilde",
            serving_description="25 pieces",
            grams_per_serving=1,
            calories=150,
            protein_g=16,
            carbs_g=15,
            fat_g=3,
            aliases=[],
        ),
    )

    resolver = FoodResolver(usda_client=FakeClient([]), off_client=FakeClient([]))
    result = resolver.resolve(session, parse_food_phrase("Wilde Protein Chips 50 count"))

    assert result.candidates
    assert result.candidates[0].source == "custom"
    assert result.candidates[0].brand == "Wilde"
