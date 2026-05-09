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
