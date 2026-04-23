from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models import CustomFoodMetadata, Food, FoodAlias
from app.schemas.foods import FoodCreate, FoodRead, FoodUpdate
from app.services.parser import normalize_text


def _apply_aliases(session: Session, food: Food, aliases: list[str]) -> None:
    existing = session.scalars(select(FoodAlias).where(FoodAlias.food_id == food.id)).all()
    existing_map = {alias.normalized_phrase: alias for alias in existing}
    desired = {normalize_text(alias): alias.strip() for alias in aliases if alias.strip()}

    for normalized, alias in desired.items():
        if normalized not in existing_map:
            session.add(FoodAlias(phrase=alias, normalized_phrase=normalized, food_id=food.id))

    for normalized, alias in existing_map.items():
        if normalized not in desired:
            session.delete(alias)


def create_food(session: Session, payload: FoodCreate) -> Food:
    food_group_key = str(uuid4()) if payload.source == "custom" else None
    food = Food(
        canonical_name=payload.canonical_name.strip(),
        normalized_name=normalize_text(payload.canonical_name),
        brand=payload.brand,
        source=payload.source,
        source_food_id=payload.source_food_id,
        serving_description=payload.serving_description,
        grams_per_serving=payload.grams_per_serving,
        calories=payload.calories,
        protein_g=payload.protein_g,
        carbs_g=payload.carbs_g,
        fat_g=payload.fat_g,
        fiber_g=payload.fiber_g,
        net_carbs_g=payload.net_carbs_g,
        raw_source_payload=payload.raw_source_payload,
        food_group_key=food_group_key,
        version=1,
        is_current=True,
    )
    session.add(food)
    session.flush()
    _apply_aliases(session, food, payload.aliases)
    if payload.source == "custom" and food_group_key:
        session.add(
            CustomFoodMetadata(
                food_group_key=food_group_key,
                current_food_id=food.id,
                authoritative_locked=payload.authoritative_locked,
                notes=payload.notes,
            )
        )
    session.commit()
    session.refresh(food)
    return food


def get_food(session: Session, food_id: int) -> Food | None:
    return session.get(Food, food_id)


def get_food_metadata(session: Session, food: Food) -> CustomFoodMetadata | None:
    if not food.food_group_key:
        return None
    return session.scalar(
        select(CustomFoodMetadata).where(CustomFoodMetadata.food_group_key == food.food_group_key)
    )


def update_food(session: Session, food_id: int, payload: FoodUpdate) -> Food:
    existing = get_food(session, food_id)
    if not existing:
        raise ValueError("Food not found")
    if existing.source != "custom":
        raise ValueError("Only custom foods can be updated in place via versioning")

    existing.is_current = False
    next_food = Food(
        canonical_name=payload.canonical_name.strip(),
        normalized_name=normalize_text(payload.canonical_name),
        brand=payload.brand,
        source="custom",
        source_food_id=existing.source_food_id,
        serving_description=payload.serving_description,
        grams_per_serving=payload.grams_per_serving,
        calories=payload.calories,
        protein_g=payload.protein_g,
        carbs_g=payload.carbs_g,
        fat_g=payload.fat_g,
        fiber_g=payload.fiber_g,
        net_carbs_g=payload.net_carbs_g,
        raw_source_payload=existing.raw_source_payload,
        food_group_key=existing.food_group_key,
        version=existing.version + 1,
        is_current=True,
    )
    session.add(next_food)
    session.flush()

    metadata = get_food_metadata(session, existing)
    if metadata:
        metadata.current_food_id = next_food.id
        metadata.authoritative_locked = payload.authoritative_locked
        metadata.notes = payload.notes

    aliases = payload.aliases or [alias.phrase for alias in existing.aliases]
    _apply_aliases(session, next_food, aliases)
    session.commit()
    session.refresh(next_food)
    return next_food


def duplicate_food_to_custom(session: Session, food_id: int) -> Food:
    original = get_food(session, food_id)
    if not original:
        raise ValueError("Food not found")
    payload = FoodCreate(
        canonical_name=original.canonical_name,
        brand=original.brand,
        serving_description=original.serving_description,
        grams_per_serving=original.grams_per_serving,
        calories=original.calories,
        protein_g=original.protein_g,
        carbs_g=original.carbs_g,
        fat_g=original.fat_g,
        fiber_g=original.fiber_g,
        net_carbs_g=original.net_carbs_g,
        aliases=[alias.phrase for alias in original.aliases],
        notes=f"Duplicated from {original.source}:{original.source_food_id or original.id}",
        authoritative_locked=False,
    )
    return create_food(session, payload)


def search_foods(session: Session, query: str | None = None, source: str | None = None) -> list[Food]:
    stmt: Select[tuple[Food]] = select(Food).where(Food.is_current.is_(True))
    if source and source != "all":
        stmt = stmt.where(Food.source == source)
    if query:
        normalized = f"%{normalize_text(query)}%"
        stmt = stmt.where(
            or_(Food.normalized_name.like(normalized), Food.brand.like(f"%{query}%"))
        )
    return session.scalars(stmt.order_by(Food.source, Food.canonical_name)).all()


def food_to_read(session: Session, food: Food) -> FoodRead:
    metadata = get_food_metadata(session, food)
    return FoodRead(
        id=food.id,
        canonical_name=food.canonical_name,
        brand=food.brand,
        source=food.source,
        source_food_id=food.source_food_id,
        serving_description=food.serving_description,
        grams_per_serving=food.grams_per_serving,
        calories=food.calories,
        protein_g=food.protein_g,
        carbs_g=food.carbs_g,
        fat_g=food.fat_g,
        fiber_g=food.fiber_g,
        net_carbs_g=food.net_carbs_g,
        aliases=[alias.phrase for alias in food.aliases],
        version=food.version,
        is_current=food.is_current,
        food_group_key=food.food_group_key,
        created_at=food.created_at,
        updated_at=food.updated_at,
        notes=metadata.notes if metadata else None,
        authoritative_locked=metadata.authoritative_locked if metadata else False,
    )


def seed_demo_data(session: Session) -> None:
    has_custom = session.scalar(select(Food.id).where(Food.source == "custom").limit(1))
    if has_custom:
        return

    demo_foods = [
        FoodCreate(
            canonical_name="Fairlife Core Power Elite 42g",
            brand="Fairlife",
            serving_description="1 bottle",
            grams_per_serving=414,
            calories=230,
            protein_g=42,
            carbs_g=9,
            fat_g=3.5,
            aliases=["Fairlife 42", "fairlife elite 42"],
            notes="Demo custom protein drink.",
            authoritative_locked=True,
        ),
        FoodCreate(
            canonical_name="Protein Coffee",
            brand=None,
            serving_description="1 mug",
            grams_per_serving=355,
            calories=180,
            protein_g=30,
            carbs_g=6,
            fat_g=4,
            aliases=["protein coffee"],
            notes="Demo recipe food.",
            authoritative_locked=True,
        ),
        FoodCreate(
            canonical_name="Ribeye Steak",
            brand=None,
            serving_description="8 oz steak",
            grams_per_serving=227,
            calories=620,
            protein_g=48,
            carbs_g=0,
            fat_g=48,
            aliases=["ribeye"],
            notes="Demo steak entry.",
        ),
        FoodCreate(
            canonical_name="Yogurt Bowl",
            brand=None,
            serving_description="1 bowl",
            grams_per_serving=280,
            calories=350,
            protein_g=27,
            carbs_g=24,
            fat_g=12,
            fiber_g=5,
            net_carbs_g=19,
            aliases=["yogurt bowl", "my yogurt bowl"],
            notes="Demo bowl with berries and chia.",
        ),
        FoodCreate(
            canonical_name="Egg",
            brand=None,
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
            aliases=["eggs", "egg"],
        ),
        FoodCreate(
            canonical_name="Butter",
            brand=None,
            serving_description="1 tbsp",
            grams_per_serving=14,
            calories=102,
            protein_g=0.1,
            carbs_g=0,
            fat_g=11.5,
            aliases=["butter"],
        ),
        FoodCreate(
            canonical_name="Bacon",
            brand=None,
            serving_description="1 slice",
            grams_per_serving=8,
            calories=43,
            protein_g=3,
            carbs_g=0.1,
            fat_g=3.3,
            aliases=["bacon", "bacon slice"],
        ),
    ]
    for food in demo_foods:
        create_food(session, food)


def list_aliases(session: Session, food: Food) -> Sequence[FoodAlias]:
    return session.scalars(select(FoodAlias).where(FoodAlias.food_id == food.id)).all()

