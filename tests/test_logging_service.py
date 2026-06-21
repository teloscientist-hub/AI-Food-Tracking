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


def test_save_meal_derives_net_carbs_snapshot_when_food_net_carbs_is_blank(session) -> None:
    banana = create_food(
        session,
        FoodCreate(
            canonical_name="Banana, Raw",
            serving_description="1 banana",
            grams_per_serving=118,
            calories=97,
            protein_g=0.74,
            carbs_g=22.71,
            fat_g=0.28,
            fiber_g=1.7,
        ),
    )

    meal = LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="3 bananas",
            meal_label="Snack 2",
            items=[LogReviewItem(parsed_phrase="bananas", quantity=3, selected_food_id=banana.id)],
        ),
    )

    item = meal.items[0]
    assert item.carbs_g_snapshot == 68.13
    assert item.fiber_g_snapshot == 5.1
    assert item.net_carbs_g_snapshot == 63.03


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


def test_serving_multiplier_scales_native_serving_count_units(session) -> None:
    asparagus = create_food(
        session,
        FoodCreate(
            canonical_name="MML Roasted Asparagus",
            serving_description="10 spears",
            grams_per_serving=1,
            calories=110,
            protein_g=3.5,
            carbs_g=6,
            fat_g=0.5,
        ),
    )

    assert serving_multiplier(10.0, "spears", asparagus) == 1.0
    assert serving_multiplier(1.0, "spear", asparagus) == 0.1
    assert serving_multiplier(5.0, "spears", asparagus) == 0.5


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


def test_serving_multiplier_converts_parsed_weight_for_count_based_food(session) -> None:
    chicken = create_food(
        session,
        FoodCreate(
            canonical_name="Chicken Breast",
            serving_description="1 breast",
            grams_per_serving=170,
            calories=280,
            protein_g=52,
            carbs_g=0,
            fat_g=6,
        ),
    )

    assert round(serving_multiplier(9.0, "oz", chicken), 4) == round((9.0 * 28.3495) / 170, 4)


def test_serving_multiplier_prefers_native_weight_unit_over_stale_grams(session) -> None:
    bacon = create_food(
        session,
        FoodCreate(
            canonical_name="Bacon",
            serving_description="1 slice",
            grams_per_serving=8,
            calories=43,
            protein_g=3,
            carbs_g=0.1,
            fat_g=3.3,
        ),
    )
    bacon.serving_description = "1 oz"
    bacon.grams_per_serving = 8

    assert serving_multiplier(1.0, "oz", bacon) == 1.0
    assert serving_multiplier(2.0, "oz", bacon) == 2.0
    assert round(serving_multiplier(28.3495, "g", bacon), 4) == 1.0


def test_save_meal_uses_parsed_weight_instead_of_previous_logged_amount(session) -> None:
    chicken = create_food(
        session,
        FoodCreate(
            canonical_name="Chicken Breast",
            serving_description="1 breast",
            grams_per_serving=170,
            calories=280,
            protein_g=52,
            carbs_g=0,
            fat_g=6,
        ),
    )
    LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="6 oz chicken breast",
            meal_label="Dinner",
            items=[
                LogReviewItem(
                    parsed_phrase="chicken breast",
                    quantity=6,
                    unit="oz",
                    quantity_text="6",
                    selected_food_id=chicken.id,
                )
            ],
        ),
    )

    meal = LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="9 oz chicken breast",
            meal_label="Dinner",
            items=[
                LogReviewItem(
                    parsed_phrase="chicken breast",
                    quantity=9,
                    unit="oz",
                    quantity_text="9",
                    selected_food_id=chicken.id,
                )
            ],
        ),
    )

    item = meal.items[0]
    assert item.quantity == 9
    assert item.unit == "oz"
    assert item.quantity_text == "9"
    assert item.grams_per_serving_snapshot == round(9 * 28.3495, 2)
    assert item.calories_snapshot == round(280 * ((9 * 28.3495) / 170), 2)


def test_save_meal_uses_custom_food_note_serving_equivalence(session) -> None:
    bacon = create_food(
        session,
        FoodCreate(
            canonical_name="Bacon",
            serving_description="1 oz",
            grams_per_serving=1,
            calories=132,
            protein_g=9.6,
            carbs_g=0.5,
            fat_g=9.9,
            notes="Three pieces of bacon typically equals one ounce.",
            aliases=["bacon"],
        ),
    )

    meal = LoggingService().save_meal(
        session,
        LogMealRequest(
            raw_input_text="three pieces of bacon",
            meal_label="Breakfast",
            items=[
                LogReviewItem(
                    parsed_phrase="bacon",
                    quantity=3,
                    unit="pieces",
                    quantity_text="three",
                    selected_food_id=bacon.id,
                )
            ],
        ),
    )

    item = meal.items[0]
    assert item.quantity == 3
    assert item.unit == "pieces"
    assert item.grams_per_serving_snapshot == 28.35
    assert item.calories_snapshot == 132.0
    assert item.protein_g_snapshot == 9.6


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
