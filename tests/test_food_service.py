import app.services.food_service as food_service
from app.models import Food, MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate, FoodUpdate
from app.services.food_service import (
    create_food,
    duplicate_food_to_custom,
    food_to_read,
    get_food_library_cards,
    remove_custom_food_from_library,
    search_foods,
    serving_description_grams,
    update_food,
)


def test_create_food_persists_aliases_and_custom_metadata(session, monkeypatch) -> None:
    monkeypatch.setattr(food_service, "_fetch_image_blob", lambda url: (b"img", "image/png"))
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Kirkland Shredded Cheddar Jack Mix",
            brand="Kirkland",
            image_url="https://example.com/cheese.png",
            icon_key="cheese",
            serving_description="1 oz",
            grams_per_serving=28,
            calories=110,
            protein_g=7,
            carbs_g=1,
            fat_g=9,
            aliases=["kirkland cheese", "cheddar jack mix"],
            notes="authoritative custom food",
            authoritative_locked=True,
        ),
    )

    assert food.source == "custom"
    assert food.version == 1
    assert food.is_current is True
    assert {alias.phrase for alias in food.aliases} == {"kirkland cheese", "cheddar jack mix"}

    persisted = session.get(Food, food.id)
    assert persisted is not None
    assert persisted.food_group_key is not None
    assert persisted.image_url == "https://example.com/cheese.png"
    assert persisted.icon_key == "cheese"


def test_serving_description_grams_handles_fractional_weight_text() -> None:
    assert serving_description_grams("190g") == 190
    assert serving_description_grams("1 portion (311.844 g)") == 311.844
    assert serving_description_grams("1/2 Ounce") == round(0.5 * 28.3495, 4)
    assert serving_description_grams("5-1/2 Ounces") == round(5.5 * 28.3495, 4)
    assert serving_description_grams("3/4 Ounce") == round(0.75 * 28.3495, 4)


def test_create_food_derives_grams_per_serving_from_weighted_serving_description(session) -> None:
    food = create_food(
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

    assert food.grams_per_serving == 190


def test_update_food_derives_grams_per_serving_from_weighted_serving_description(session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Protein Yogurt",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=140,
            protein_g=20,
            carbs_g=8,
            fat_g=3,
        ),
    )

    updated = update_food(
        session,
        food.id,
        FoodUpdate(
            canonical_name="Protein Yogurt",
            serving_description="190 g",
            grams_per_serving=1,
            calories=140,
            protein_g=20,
            carbs_g=8,
            fat_g=3,
        ),
    )

    assert updated.grams_per_serving == 190


def test_update_food_versions_custom_food_and_replaces_aliases(session, monkeypatch) -> None:
    monkeypatch.setattr(food_service, "_fetch_image_blob", lambda url: (b"img", "image/png"))
    original = create_food(
        session,
        FoodCreate(
            canonical_name="Protein Coffee",
            serving_description="1 mug",
            grams_per_serving=355,
            calories=180,
            protein_g=30,
            carbs_g=6,
            fat_g=4,
            aliases=["protein coffee"],
            notes="v1",
            authoritative_locked=True,
        ),
    )

    updated = update_food(
        session,
        original.id,
        FoodUpdate(
            canonical_name="Protein Coffee Deluxe",
            image_url="https://example.com/coffee.png",
            icon_key="coffee",
            serving_description="1 mug",
            grams_per_serving=355,
            calories=200,
            protein_g=32,
            carbs_g=7,
            fat_g=5,
            aliases=["protein coffee deluxe"],
            notes="v2",
            authoritative_locked=False,
        ),
    )

    stale = session.get(Food, original.id)
    assert stale is not None
    assert stale.is_current is False
    assert updated.id != original.id
    assert updated.version == 2
    assert updated.is_current is True
    assert updated.image_url == "https://example.com/coffee.png"
    assert updated.icon_key == "coffee"
    assert {alias.phrase for alias in updated.aliases} == {"protein coffee deluxe"}


def test_duplicate_food_to_custom_copies_external_macros(session, monkeypatch) -> None:
    monkeypatch.setattr(food_service, "_fetch_image_blob", lambda url: (b"img", "image/png"))
    external = create_food(
        session,
        FoodCreate(
            canonical_name="Ratio Protein Yogurt Blueberry",
            brand="Ratio",
            image_url="https://example.com/ratio.png",
            icon_key="yogurt",
            serving_description="1 container",
            grams_per_serving=150,
            calories=170,
            protein_g=25,
            carbs_g=8,
            fat_g=4,
            source="openfoodfacts",
            source_food_id="ratio-123",
            raw_source_payload={"source": "off"},
        ),
    )

    duplicate = duplicate_food_to_custom(session, external.id)

    assert duplicate.source == "custom"
    assert duplicate.canonical_name == external.canonical_name
    assert duplicate.calories == external.calories
    assert duplicate.protein_g == external.protein_g
    assert duplicate.image_url == "https://example.com/ratio.png"
    assert duplicate.icon_key == "yogurt"
    assert food_to_read(session, duplicate).notes == "Duplicated from openfoodfacts:ratio-123"
    assert food_to_read(session, duplicate).icon_symbol == "🥣"


def test_search_foods_filters_by_query_and_source(session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="Premier Protein Cafe Latte",
            brand="Premier Protein",
            serving_description="1 shake",
            grams_per_serving=325,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
            source="openfoodfacts",
            source_food_id="premier-1",
        ),
    )
    create_food(
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

    results = search_foods(session, query="premier", source="openfoodfacts")

    assert len(results) == 1
    assert results[0].canonical_name == "Premier Protein Cafe Latte"


def test_create_and_update_food_store_uploaded_image_bytes(session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Butter",
            serving_description="1 tbsp",
            grams_per_serving=14,
            calories=102,
            protein_g=0.1,
            carbs_g=0,
            fat_g=11.5,
            image_data=b"original-bytes",
            image_content_type="image/png",
        ),
    )

    assert food.image_data == b"original-bytes"
    assert food.image_content_type == "image/png"

    updated = update_food(
        session,
        food.id,
        FoodUpdate(
            canonical_name="Butter",
            serving_description="1 tbsp",
            grams_per_serving=14,
            calories=102,
            protein_g=0.1,
            carbs_g=0,
            fat_g=11.5,
            image_data=b"updated-bytes",
            image_content_type="image/jpeg",
        ),
    )

    assert updated.image_data == b"updated-bytes"
    assert updated.image_content_type == "image/jpeg"
    assert updated.version == 2


def test_remove_custom_food_from_library_hides_it_from_current_search(session) -> None:
    custom = create_food(
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

    before = search_foods(session, source="custom")
    assert [food.id for food in before] == [custom.id]

    remove_custom_food_from_library(session, custom.id)

    after = search_foods(session, source="custom")
    assert after == []

    hidden = session.get(Food, custom.id)
    assert hidden is not None
    assert hidden.is_current is False


def test_get_food_library_cards_previously_logged_sorts_by_last_logged_at(session) -> None:
    older = create_food(
        session,
        FoodCreate(
            canonical_name="Older Logged Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=10,
            protein_g=1,
            carbs_g=1,
            fat_g=1,
        ),
    )
    newer = create_food(
        session,
        FoodCreate(
            canonical_name="Newer Logged Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=20,
            protein_g=2,
            carbs_g=2,
            fat_g=2,
        ),
    )

    old_entry = MealEntry(raw_input_text="old", meal_label="Breakfast")
    session.add(old_entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=old_entry.id,
            food_id=older.id,
            parsed_phrase="older",
            normalized_phrase="older",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=older.canonical_name,
            resolved_source=older.source,
            calories_snapshot=10,
            protein_g_snapshot=1,
            carbs_g_snapshot=1,
            fat_g_snapshot=1,
        )
    )

    new_entry = MealEntry(raw_input_text="new", meal_label="Breakfast")
    session.add(new_entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=new_entry.id,
            food_id=newer.id,
            parsed_phrase="newer",
            normalized_phrase="newer",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=newer.canonical_name,
            resolved_source=newer.source,
            calories_snapshot=20,
            protein_g_snapshot=2,
            carbs_g_snapshot=2,
            fat_g_snapshot=2,
        )
    )
    session.commit()

    cards = get_food_library_cards(session, source="custom", sort_by="previously_logged")

    assert cards[0]["food"].canonical_name == "Newer Logged Food"
    assert cards[1]["food"].canonical_name == "Older Logged Food"
