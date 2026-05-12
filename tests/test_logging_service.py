from app.schemas.foods import FoodCreate
from app.schemas.logging import LogMealRequest, LogReviewItem
from app.services.food_service import create_food
from app.services.logging_service import LoggingService, serving_multiplier


def test_save_meal_allows_unresolved_items(session) -> None:
    egg = create_food(
        session,
        FoodCreate(
            canonical_name="Egg",
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
            aliases=["egg"],
        ),
    )

    meal = LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="2 eggs, mystery sauce",
            meal_label="Breakfast",
            items=[
                LogReviewItem(parsed_phrase="eggs", quantity=2, selected_food_id=egg.id),
                LogReviewItem(parsed_phrase="mystery sauce", quantity=1, selected_food_id=None),
            ],
        ),
    )

    assert len(meal.items) == 2
    resolved = next(item for item in meal.items if item.food_id is not None)
    unresolved = next(item for item in meal.items if item.food_id is None)
    assert resolved.calories_snapshot == 144
    assert unresolved.resolution_status == "unresolved"
    assert unresolved.calories_snapshot == 0.0


def test_save_meal_adds_alias_when_always_map_is_selected(session) -> None:
    yogurt = create_food(
        session,
        FoodCreate(
            canonical_name="Ratio Protein Yogurt Blueberry",
            brand="Ratio",
            serving_description="1 container",
            grams_per_serving=150,
            calories=170,
            protein_g=25,
            carbs_g=8,
            fat_g=4,
        ),
    )

    meal = LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="ratio blueberry yogurt",
            meal_label="Breakfast",
            items=[
                LogReviewItem(
                    parsed_phrase="ratio blueberry yogurt",
                    quantity=1,
                    selected_food_id=yogurt.id,
                    always_map=True,
                )
            ],
        ),
    )

    assert len(meal.items) == 1
    assert any(alias.phrase == "ratio blueberry yogurt" for alias in yogurt.aliases)


def test_persist_external_candidate_creates_external_food(session) -> None:
    created = LoggingService().persist_external_candidate(
        session,
        0,
        [
            {
                "canonical_name": "Premier Protein Cafe Latte",
                "brand": "Premier Protein",
                "source": "openfoodfacts",
                "source_food_id": "premier-123",
                "serving_description": "1 bottle",
                "grams_per_serving": 325.0,
                "calories": 160.0,
                "protein_g": 30.0,
                "carbs_g": 5.0,
                "fat_g": 3.0,
                "fiber_g": 1.0,
                "net_carbs_g": 4.0,
                "raw_payload": {"id": "payload"},
            }
        ],
    )

    assert created.source == "openfoodfacts"
    assert created.source_food_id == "premier-123"
    assert created.protein_g == 30.0
    assert created.net_carbs_g == 4.0


def test_save_external_candidate_as_custom_creates_custom_food_with_alias(session) -> None:
    created = LoggingService().save_external_candidate_as_custom(
        session,
        0,
        [
            {
                "canonical_name": "Premier Protein Cafe Latte",
                "brand": "Premier Protein",
                "source": "openfoodfacts",
                "source_food_id": "premier-123",
                "serving_description": "1 bottle",
                "grams_per_serving": 325.0,
                "calories": 160.0,
                "protein_g": 30.0,
                "carbs_g": 5.0,
                "fat_g": 3.0,
                "fiber_g": 1.0,
                "net_carbs_g": 4.0,
                "raw_payload": {"id": "payload"},
            }
        ],
        alias_phrase="pure protein cafe latte",
    )

    assert created.source == "custom"
    assert created.canonical_name == "Premier Protein Cafe Latte"
    assert created.brand == "Premier Protein"
    assert any(alias.phrase == "pure protein cafe latte" for alias in created.aliases)


def test_serving_multiplier_converts_unit_weight_against_serving_size(session) -> None:
    butter = create_food(
        session,
        FoodCreate(
            canonical_name="Butter",
            serving_description="1 tbsp",
            grams_per_serving=14,
            calories=102,
            protein_g=0.1,
            carbs_g=0,
            fat_g=11.5,
        ),
    )

    assert serving_multiplier(1.0, "tbsp", butter) == 1.0
    assert round(serving_multiplier(2.0, "oz", butter), 2) == round((2.0 * 28.3495) / 14, 2)


def test_serving_multiplier_uses_derived_weighted_serving_size(session) -> None:
    yogurt = create_food(
        session,
        FoodCreate(
            canonical_name="Chobani 20 g protein yogurt",
            serving_description="190g",
            grams_per_serving=1,
            calories=140,
            protein_g=20,
            carbs_g=8,
            fat_g=3,
        ),
    )

    assert yogurt.grams_per_serving == 190
    assert round(serving_multiplier(12.0, "oz", yogurt), 4) == round((12.0 * 28.3495) / 190, 4)
