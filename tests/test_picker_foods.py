from datetime import UTC, datetime, timedelta

from app.models import Food, MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate
from app.services.food_service import create_food, get_food_library_cards, get_picker_foods


def test_picker_foods_prefers_recent_logged_foods_and_last_amount(session) -> None:
    first = create_food(
        session,
        FoodCreate(
            canonical_name="Protein Coffee",
            serving_description="1 mug",
            grams_per_serving=355,
            calories=180,
            protein_g=30,
            carbs_g=6,
            fat_g=4,
        ),
    )
    second = create_food(
        session,
        FoodCreate(
            canonical_name="Egg",
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
        ),
    )
    third = create_food(
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

    older_entry = MealEntry(raw_input_text="2 Protein Coffee", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=1))
    newer_entry = MealEntry(raw_input_text="5 oz Egg", meal_label="Lunch", logged_at=datetime.now(UTC))
    session.add_all([older_entry, newer_entry])
    session.flush()
    session.add_all(
        [
            MealEntryItem(
                meal_entry_id=older_entry.id,
                food_id=first.id,
                parsed_phrase="Protein Coffee",
                normalized_phrase="protein coffee",
                quantity=2.0,
                unit=None,
            ),
            MealEntryItem(
                meal_entry_id=newer_entry.id,
                food_id=second.id,
                parsed_phrase="Egg",
                normalized_phrase="egg",
                quantity=5.0,
                unit="oz",
            ),
        ]
    )
    session.commit()

    cards = get_picker_foods(session)

    assert cards[0]["food"].id == second.id
    assert cards[0]["quick_quantity"] == 5.0
    assert cards[0]["quick_unit"] == "oz"
    assert [option["value"] for option in cards[0]["unit_options"]][:3] == ["oz", "egg", "g"]
    assert cards[1]["food"].id == first.id
    assert cards[2]["food"].id == third.id
    assert cards[2]["quick_unit"] == "tbsp"
    assert cards[2]["unit_options"][0]["value"] == "tbsp"


def test_picker_foods_orders_by_item_add_time_when_logged_dates_match(session) -> None:
    older = create_food(
        session,
        FoodCreate(
            canonical_name="Alpha Earlier Snack",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=3,
        ),
    )
    recent = create_food(
        session,
        FoodCreate(
            canonical_name="Zulu Recent Daily Log Snack",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=150,
            protein_g=20,
            carbs_g=6,
            fat_g=4,
        ),
    )
    food_created_at = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    for food in [older, recent]:
        food.created_at = food_created_at
        food.updated_at = food_created_at

    shared_logged_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    older_used_at = datetime(2026, 5, 25, 18, 0, tzinfo=UTC)
    recent_used_at = datetime(2026, 5, 26, 8, 0, tzinfo=UTC)
    older_entry = MealEntry(
        raw_input_text="older snack",
        meal_label="Snack 1",
        logged_at=shared_logged_at,
        created_at=older_used_at,
    )
    recent_entry = MealEntry(
        raw_input_text="recent snack",
        meal_label="Snack 1",
        logged_at=shared_logged_at,
        created_at=recent_used_at,
    )
    session.add_all([older_entry, recent_entry])
    session.flush()
    session.add_all(
        [
            MealEntryItem(
                meal_entry_id=older_entry.id,
                food_id=older.id,
                parsed_phrase=older.canonical_name,
                normalized_phrase=older.normalized_name,
                quantity=1.0,
                unit="serving",
                created_at=older_used_at,
            ),
            MealEntryItem(
                meal_entry_id=recent_entry.id,
                food_id=recent.id,
                parsed_phrase=recent.canonical_name,
                normalized_phrase=recent.normalized_name,
                quantity=1.0,
                unit="serving",
                created_at=recent_used_at,
            ),
        ]
    )
    session.commit()

    cards = get_picker_foods(session)

    assert cards[0]["food"].id == recent.id
    assert cards[1]["food"].id == older.id


def test_picker_foods_orders_filtered_results_by_recent_parser_usage(session) -> None:
    older = create_food(
        session,
        FoodCreate(
            canonical_name="Alpha Query Protein Snack",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=3,
        ),
    )
    recent = create_food(
        session,
        FoodCreate(
            canonical_name="Zulu Query Protein Shake",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
        ),
    )
    food_created_at = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    for food in [older, recent]:
        food.created_at = food_created_at
        food.updated_at = food_created_at

    older_used_at = datetime(2026, 5, 25, 18, 0, tzinfo=UTC)
    recent_used_at = datetime(2026, 5, 26, 8, 0, tzinfo=UTC)
    older_entry = MealEntry(
        raw_input_text="older query protein snack",
        meal_label="Snack 1",
        logged_at=older_used_at,
        created_at=older_used_at,
    )
    recent_entry = MealEntry(
        raw_input_text="recent query protein shake",
        meal_label="Snack 1",
        logged_at=recent_used_at,
        created_at=recent_used_at,
    )
    session.add_all([older_entry, recent_entry])
    session.flush()
    session.add_all(
        [
            MealEntryItem(
                meal_entry_id=older_entry.id,
                food_id=older.id,
                parsed_phrase=older.canonical_name,
                normalized_phrase=older.normalized_name,
                quantity=1.0,
                unit="serving",
                created_at=older_used_at,
            ),
            MealEntryItem(
                meal_entry_id=recent_entry.id,
                food_id=recent.id,
                parsed_phrase=recent.canonical_name,
                normalized_phrase=recent.normalized_name,
                quantity=1.0,
                unit="serving",
                created_at=recent_used_at,
            ),
        ]
    )
    session.commit()

    cards = get_picker_foods(session, query="query protein")

    assert cards[0]["food"].id == recent.id
    assert cards[1]["food"].id == older.id


def test_picker_foods_uses_native_serving_quantity_for_count_units(session) -> None:
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

    cards = get_picker_foods(session, query="asparagus")

    assert cards[0]["food"].id == asparagus.id
    assert cards[0]["quick_quantity"] == 10.0
    assert cards[0]["quick_unit"] == "spears"
    assert cards[0]["native_quantity"] == 10.0
    assert cards[0]["native_unit"] == "spears"
    assert cards[0]["unit_options"][0]["value"] == "spears"


def test_picker_foods_uses_last_input_quantity_instead_of_merged_total(session) -> None:
    sausage = create_food(
        session,
        FoodCreate(
            canonical_name="Chicken Sausage Parmesan Cracked Pepper",
            serving_description="1 piece",
            grams_per_serving=85,
            calories=140,
            protein_g=16,
            carbs_g=2,
            fat_g=8,
        ),
    )
    entry = MealEntry(raw_input_text="picker adds", meal_label="Dinner", logged_at=datetime.now(UTC))
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=sausage.id,
            parsed_phrase=sausage.canonical_name,
            normalized_phrase=sausage.normalized_name,
            quantity=11.0,
            unit="piece",
            quantity_text="1",
        )
    )
    session.commit()

    cards = get_picker_foods(session, query="chicken sausage")

    assert cards[0]["food"].id == sausage.id
    assert cards[0]["quick_quantity"] == 1.0
    assert cards[0]["quick_unit"] == "piece"


def test_picker_foods_exposes_note_serving_equivalences(session) -> None:
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
        ),
    )

    cards = get_picker_foods(session, query="bacon")

    assert cards[0]["food"].id == bacon.id
    assert [option["value"] for option in cards[0]["unit_options"]][:3] == ["oz", "pieces", "g"]
    assert cards[0]["serving_equivalences"] == [
        {
            "sourceQuantity": 3.0,
            "sourceUnit": "pieces",
            "targetQuantity": 1.0,
            "targetUnit": "oz",
        }
    ]


def test_picker_foods_can_hold_page_order_after_logging_from_picker(session) -> None:
    foods = [
        create_food(
            session,
            FoodCreate(
                canonical_name=name,
                serving_description="1 serving",
                grams_per_serving=1,
                calories=100,
                protein_g=10,
                carbs_g=5,
                fat_g=3,
            ),
        )
        for name in ["Stable Alpha", "Stable Beta", "Stable Gamma"]
    ]
    initial_cards = get_picker_foods(session)
    stable_order = [card["food"].id for card in initial_cards]
    logged_food_id = stable_order[-1]

    entry = MealEntry(raw_input_text="stable picker add", meal_label="Breakfast", logged_at=datetime.now(UTC))
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=logged_food_id,
            parsed_phrase="stable picker add",
            normalized_phrase="stable picker add",
            quantity=2.0,
            unit="serving",
        )
    )
    session.commit()

    resorted_cards = get_picker_foods(session)
    stable_cards = get_picker_foods(session, stable_order=stable_order)

    assert foods
    assert resorted_cards[0]["food"].id == logged_food_id
    assert [card["food"].id for card in stable_cards] == stable_order
    assert stable_cards[-1]["quick_quantity"] == 2.0


def test_picker_foods_exposes_image_url_from_source_payload(session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Blueberry Yogurt",
            serving_description="1 container",
            grams_per_serving=150,
            calories=170,
            protein_g=25,
            carbs_g=8,
            fat_g=4,
            source="openfoodfacts",
            source_food_id="abc",
            raw_source_payload={"image_front_url": "https://example.com/yogurt.png"},
        ),
    )

    cards = get_picker_foods(session, query="blueberry")

    assert cards[0]["food"].id == food.id
    assert cards[0]["food"].image_url == "https://example.com/yogurt.png"


def test_picker_foods_surfaces_new_custom_food_created_after_logs(session) -> None:
    logged = create_food(
        session,
        FoodCreate(
            canonical_name="Protein Coffee",
            serving_description="1 mug",
            grams_per_serving=355,
            calories=180,
            protein_g=30,
            carbs_g=6,
            fat_g=4,
        ),
    )
    meal_entry = MealEntry(raw_input_text="protein coffee", meal_label="Breakfast", logged_at=datetime.now(UTC))
    session.add(meal_entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=meal_entry.id,
            food_id=logged.id,
            parsed_phrase="protein coffee",
            normalized_phrase="protein coffee",
            quantity=1.0,
            unit=None,
        )
    )
    session.commit()

    custom = create_food(
        session,
        FoodCreate(
            canonical_name="Fresh Custom Shake",
            serving_description="1 bottle",
            grams_per_serving=330,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
        ),
    )

    cards = get_picker_foods(session)

    assert cards[0]["food"].id == custom.id
    assert cards[1]["food"].id == logged.id
    assert cards[1]["quick_quantity"] == 1.0


def test_food_library_prefers_higher_log_count_then_recency(session) -> None:
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
        ),
    )
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

    old_entry = MealEntry(raw_input_text="egg", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=3))
    mid_entry = MealEntry(raw_input_text="butter", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=2))
    new_entry = MealEntry(raw_input_text="bacon", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=1))
    newest_entry = MealEntry(raw_input_text="egg again", meal_label="Breakfast", logged_at=datetime.now(UTC))
    session.add_all([old_entry, mid_entry, new_entry, newest_entry])
    session.flush()
    session.add_all(
        [
            MealEntryItem(meal_entry_id=old_entry.id, food_id=egg.id, parsed_phrase="egg", normalized_phrase="egg", quantity=1.0, unit=None),
            MealEntryItem(meal_entry_id=mid_entry.id, food_id=butter.id, parsed_phrase="butter", normalized_phrase="butter", quantity=1.0, unit=None),
            MealEntryItem(meal_entry_id=new_entry.id, food_id=bacon.id, parsed_phrase="bacon", normalized_phrase="bacon", quantity=1.0, unit=None),
            MealEntryItem(meal_entry_id=newest_entry.id, food_id=egg.id, parsed_phrase="egg", normalized_phrase="egg", quantity=1.0, unit=None),
        ]
    )
    session.commit()

    cards = get_food_library_cards(session)

    assert cards[0]["food"].id == egg.id
    assert cards[0]["log_count"] == 2
    assert cards[1]["food"].id == bacon.id
    assert cards[1]["log_count"] == 1
    assert cards[2]["food"].id == butter.id


def test_food_library_surfaces_recent_custom_food_creation_above_older_logged_items(session) -> None:
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
        ),
    )

    old_entry = MealEntry(raw_input_text="butter", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=2))
    newer_entry = MealEntry(raw_input_text="egg", meal_label="Breakfast", logged_at=datetime.now(UTC) - timedelta(days=1))
    session.add_all([old_entry, newer_entry])
    session.flush()
    session.add_all(
        [
            MealEntryItem(meal_entry_id=old_entry.id, food_id=butter.id, parsed_phrase="butter", normalized_phrase="butter", quantity=1.0, unit=None),
            MealEntryItem(meal_entry_id=newer_entry.id, food_id=egg.id, parsed_phrase="egg", normalized_phrase="egg", quantity=1.0, unit=None),
        ]
    )
    session.commit()

    custom = create_food(
        session,
        FoodCreate(
            canonical_name="Kirkland Shredded Cheddar and Jack Mix",
            brand="Kirkland",
            serving_description="1 oz",
            grams_per_serving=28,
            calories=110,
            protein_g=7,
            carbs_g=1,
            fat_g=9,
            aliases=["kirkland cheese"],
            authoritative_locked=True,
        ),
    )

    cards = get_food_library_cards(session)

    assert cards[0]["food"].id == custom.id
    assert cards[1]["food"].id == egg.id
