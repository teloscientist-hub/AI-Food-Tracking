from app.models import Food
from app.schemas.foods import FoodCreate, FoodUpdate
from app.services.food_service import create_food, duplicate_food_to_custom, food_to_read, search_foods, update_food


def test_create_food_persists_aliases_and_custom_metadata(session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Kirkland Shredded Cheddar Jack Mix",
            brand="Kirkland",
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


def test_update_food_versions_custom_food_and_replaces_aliases(session) -> None:
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
    assert {alias.phrase for alias in updated.aliases} == {"protein coffee deluxe"}


def test_duplicate_food_to_custom_copies_external_macros(session) -> None:
    external = create_food(
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
    assert food_to_read(session, duplicate).notes == "Duplicated from openfoodfacts:ratio-123"


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
