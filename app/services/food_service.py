from __future__ import annotations

from collections.abc import Sequence
import re
from uuid import uuid4

import httpx
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import CustomFoodMetadata, Food, FoodAlias, MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate, FoodRead, FoodUpdate
from app.services.food_icons import food_icon_symbol
from app.services.parser import normalize_text


GRAM_UNIT_OPTIONS = [
    ("g", "grams"),
    ("oz", "oz"),
]

WEIGHT_UNIT_TO_GRAMS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
}


def _quantity_from_match(match: re.Match[str]) -> float | None:
    if match.group("mixed_whole"):
        denominator = float(match.group("mixed_den"))
        if denominator == 0:
            return None
        return float(match.group("mixed_whole")) + (float(match.group("mixed_num")) / denominator)
    if match.group("frac_num"):
        denominator = float(match.group("frac_den"))
        if denominator == 0:
            return None
        return float(match.group("frac_num")) / denominator
    return float(match.group("decimal"))


def _unit_key(unit: str | None) -> str:
    if not unit:
        return ""
    cleaned = re.sub(r"\s+", " ", unit.strip().lower())
    if cleaned.endswith("ies"):
        return f"{cleaned[:-3]}y"
    if cleaned.endswith("s") and not cleaned.endswith("ss"):
        return cleaned[:-1]
    return cleaned


def serving_description_amount_unit(serving_description: str | None) -> tuple[float, str] | None:
    if not serving_description:
        return None
    match = re.match(
        r"^\s*"
        r"(?:"
        r"(?P<mixed_whole>\d+)[-\s]+(?P<mixed_num>\d+)/(?P<mixed_den>\d+)"
        r"|(?P<frac_num>\d+)/(?P<frac_den>\d+)"
        r"|(?P<decimal>\d+(?:\.\d+)?)"
        r")"
        r"\s*(?P<unit>[a-z]+(?:\s+[a-z]+)?)\b",
        serving_description,
        flags=re.I,
    )
    if not match:
        return None
    quantity = _quantity_from_match(match)
    if not quantity or quantity <= 0:
        return None
    unit = re.sub(r"\s+", " ", match.group("unit").strip().lower())
    first_word = unit.split()[0]
    if first_word in WEIGHT_UNIT_TO_GRAMS:
        unit = first_word
    return quantity, unit


def serving_unit_matches(left: str | None, right: str | None) -> bool:
    return bool(_unit_key(left)) and _unit_key(left) == _unit_key(right)


def serving_description_grams(serving_description: str | None) -> float | None:
    if not serving_description:
        return None
    match = re.search(
        r"(?<![a-z0-9/])"
        r"(?:"
        r"(?P<mixed_whole>\d+)[-\s]+(?P<mixed_num>\d+)/(?P<mixed_den>\d+)"
        r"|(?P<frac_num>\d+)/(?P<frac_den>\d+)"
        r"|(?P<decimal>\d+(?:\.\d+)?)"
        r")"
        r"\s*(?P<unit>g|gram|grams|oz|ounce|ounces)\b",
        serving_description,
        flags=re.I,
    )
    if not match:
        return None
    amount = _quantity_from_match(match)
    if amount is None:
        return None
    unit = match.group("unit").lower()
    return round(amount * WEIGHT_UNIT_TO_GRAMS[unit], 4)


def _grams_per_serving_from_payload(payload: FoodCreate | FoodUpdate) -> float:
    explicit_weight = serving_description_grams(payload.serving_description)
    if explicit_weight and (payload.grams_per_serving is None or payload.grams_per_serving <= 1.0):
        return explicit_weight
    return payload.grams_per_serving or 1.0


def _timestamp_value(value: object) -> float:
    if value is None:
        return 0.0
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        return float(timestamp())
    return 0.0


def _source_payload_image_url(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    direct_keys = ["image_url", "image_front_url", "image_small_url"]
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    selected_images = payload.get("selected_images")
    if isinstance(selected_images, dict):
        front = selected_images.get("front")
        if isinstance(front, dict):
            display = front.get("display")
            if isinstance(display, dict):
                for value in display.values():
                    if isinstance(value, str) and value:
                        return value
    return None


def _fetch_image_blob(image_url: str | None) -> tuple[bytes | None, str | None]:
    if not image_url or not re.match(r"^https?://", image_url, flags=re.I):
        return (None, None)
    try:
        timeout = httpx.Timeout(connect=1.5, read=3.0, write=3.0, pool=1.5)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
            if not content_type.startswith("image/"):
                return (None, None)
            return (response.content, content_type)
    except Exception:
        return (None, None)


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
    source_image_url = payload.image_url or _source_payload_image_url(payload.raw_source_payload)
    image_data = payload.image_data
    image_content_type = payload.image_content_type
    if image_data is None:
        image_data, image_content_type = _fetch_image_blob(source_image_url)
    food = Food(
        canonical_name=payload.canonical_name.strip(),
        normalized_name=normalize_text(payload.canonical_name),
        brand=payload.brand,
        source=payload.source,
        source_food_id=payload.source_food_id,
        image_url=source_image_url,
        image_content_type=image_content_type,
        image_data=image_data,
        icon_key=payload.icon_key,
        serving_description=payload.serving_description,
        grams_per_serving=_grams_per_serving_from_payload(payload),
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
    source_image_url = payload.image_url or existing.image_url or _source_payload_image_url(existing.raw_source_payload)
    image_data = payload.image_data
    image_content_type = payload.image_content_type
    if image_data is None and source_image_url != existing.image_url:
        image_data, image_content_type = _fetch_image_blob(source_image_url)
    next_food = Food(
        canonical_name=payload.canonical_name.strip(),
        normalized_name=normalize_text(payload.canonical_name),
        brand=payload.brand,
        source="custom",
        source_food_id=existing.source_food_id,
        image_url=source_image_url,
        image_content_type=image_content_type or existing.image_content_type,
        image_data=image_data or existing.image_data,
        icon_key=payload.icon_key,
        serving_description=payload.serving_description,
        grams_per_serving=_grams_per_serving_from_payload(payload),
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
        image_url=original.image_url or _source_payload_image_url(original.raw_source_payload),
        image_data=original.image_data,
        image_content_type=original.image_content_type,
        icon_key=original.icon_key,
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


def remove_custom_food_from_library(session: Session, food_id: int) -> Food:
    food = get_food(session, food_id)
    if not food:
        raise ValueError("Food not found")
    if food.source != "custom":
        raise ValueError("Only custom foods can be removed from the custom library")
    food.is_current = False
    session.commit()
    session.refresh(food)
    return food


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


def get_picker_foods(
    session: Session,
    query: str | None = None,
    source: str | None = None,
    stable_order: Sequence[int] | None = None,
) -> list[dict]:
    foods = search_foods(session, query, source)
    recent_map = _recent_log_map(session)
    if query:
        cards = [_picker_card(session, food, recent_map.get(food.id)) for food in foods]
        return _apply_picker_stable_order(cards, stable_order)

    newest_meal_created_at = _newest_meal_entry_created_at(session)

    def picker_sort_key(food: Food) -> tuple[int, float, str]:
        recent_entry = recent_map.get(food.id)
        food_activity = max(_timestamp_value(food.updated_at), _timestamp_value(food.created_at))
        if food_activity > _timestamp_value(newest_meal_created_at):
            return (0, -food_activity, food.canonical_name.lower())
        if recent_entry:
            return (1, -_timestamp_value(recent_entry[1]), food.canonical_name.lower())
        return (2, -food_activity, food.canonical_name.lower())

    ordered_foods = sorted(foods, key=picker_sort_key)
    cards = [_picker_card(session, food, recent_map.get(food.id)) for food in ordered_foods]
    return _apply_picker_stable_order(cards, stable_order)


def _apply_picker_stable_order(cards: list[dict], stable_order: Sequence[int] | None) -> list[dict]:
    if not stable_order:
        return cards
    by_food_id = {card["food"].id: card for card in cards}
    ordered: list[dict] = []
    seen: set[int] = set()
    for food_id in stable_order:
        if food_id in by_food_id and food_id not in seen:
            ordered.append(by_food_id[food_id])
            seen.add(food_id)
    ordered.extend(card for card in cards if card["food"].id not in seen)
    return ordered


def get_food_library_cards(
    session: Session,
    query: str | None = None,
    source: str | None = None,
    sort_by: str = "previously_logged",
) -> list[dict]:
    foods = search_foods(session, query, source)
    log_stats = _food_log_stats_map(session)
    cards: list[dict] = []
    for food in foods:
        stats = log_stats.get(food.id, {"log_count": 0, "last_logged_at": None})
        activity_at = max(
            [stats["last_logged_at"], food.updated_at, food.created_at],
            key=_timestamp_value,
        )
        cards.append(
            {
                "food": food_to_read(session, food),
                "log_count": int(stats["log_count"]),
                "last_logged_at": stats["last_logged_at"],
                "activity_at": activity_at,
            }
        )

    if sort_by == "frequently_logged":
        cards.sort(
            key=lambda card: (
                -card["log_count"],
                -_timestamp_value(card["last_logged_at"]),
                card["food"].canonical_name.lower(),
            )
        )
    elif sort_by == "frequent_breakfast":
        cards.sort(
            key=lambda card: (
                -_timestamp_value(card["last_logged_at"]),
                -card["log_count"],
                card["food"].canonical_name.lower(),
            )
        )
    else:
        cards.sort(
            key=lambda card: (
                -_timestamp_value(card["activity_at"]),
                -_timestamp_value(card["last_logged_at"]),
                -card["log_count"],
                card["food"].canonical_name.lower(),
            )
        )
    return cards


def _recent_log_map(session: Session) -> dict[int, tuple[MealEntryItem, object]]:
    rows = (
        session.query(MealEntryItem, MealEntry)
        .join(MealEntry, MealEntry.id == MealEntryItem.meal_entry_id)
        .filter(MealEntryItem.food_id.is_not(None))
        .order_by(MealEntry.logged_at.desc(), MealEntryItem.id.desc())
        .all()
    )
    recent: dict[int, tuple[MealEntryItem, object]] = {}
    for meal_item, meal_entry in rows:
        if meal_item.food_id is None or meal_item.food_id in recent:
            continue
        recent[meal_item.food_id] = (meal_item, meal_entry.logged_at)
    return recent


def _newest_meal_entry_created_at(session: Session) -> object:
    return session.query(func.max(MealEntry.created_at)).scalar()


def _food_log_stats_map(session: Session) -> dict[int, dict]:
    rows = (
        session.query(
            MealEntryItem.food_id,
            func.count(MealEntryItem.id),
            func.max(MealEntry.logged_at),
        )
        .join(MealEntry, MealEntry.id == MealEntryItem.meal_entry_id)
        .filter(MealEntryItem.food_id.is_not(None))
        .group_by(MealEntryItem.food_id)
        .all()
    )
    return {
        int(food_id): {"log_count": int(log_count), "last_logged_at": last_logged_at}
        for food_id, log_count, last_logged_at in rows
        if food_id is not None
    }


def _format_quantity(value: float) -> str:
    return f"{value:g}"


def _picker_card(session: Session, food: Food, recent_entry: tuple[MealEntryItem, object] | None) -> dict:
    food_read = food_to_read(session, food)
    serving_measure = serving_description_amount_unit(food.serving_description)
    native_quantity = serving_measure[0] if serving_measure else 1.0
    native_unit = serving_measure[1] if serving_measure else _native_serving_unit(food.serving_description)
    if recent_entry:
        meal_item, logged_at = recent_entry
        if meal_item.unit:
            quick_quantity = meal_item.quantity
            quick_unit = meal_item.unit
        elif native_unit:
            quick_quantity = meal_item.quantity * native_quantity
            quick_unit = native_unit
        else:
            quick_quantity = meal_item.quantity
            quick_unit = None
        quick_label = f"{_format_quantity(quick_quantity)} {quick_unit}".strip() if quick_unit else f"{_format_quantity(meal_item.quantity)} {food.serving_description}"
        last_logged_at = logged_at
    else:
        quick_quantity = native_quantity if native_unit else 1.0
        quick_unit = native_unit
        quick_label = f"{_format_quantity(quick_quantity)} {quick_unit}".strip() if quick_unit else f"1 {food.serving_description}"
        last_logged_at = None
    unit_options = _picker_unit_options(native_unit, quick_unit)
    return {
        "food": food_read,
        "quick_quantity": quick_quantity,
        "quick_unit": quick_unit,
        "quick_label": quick_label,
        "last_logged_at": last_logged_at,
        "native_quantity": native_quantity,
        "native_unit": native_unit,
        "unit_options": unit_options,
    }


def _native_serving_unit(serving_description: str | None) -> str | None:
    serving_measure = serving_description_amount_unit(serving_description)
    if serving_measure:
        return serving_measure[1]
    if not serving_description:
        return None
    text = serving_description.strip().lower()
    match = re.match(r"^(?:\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s+)?([a-z]+(?:\s+[a-z]+)?)", text)
    if not match:
        return None
    native = match.group(1).strip()
    if native in {"x", "of"}:
        return None
    return native


def _picker_unit_options(native_unit: str | None, recent_unit: str | None) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(value: str | None, label: str | None = None) -> None:
        if not value:
            return
        cleaned = value.strip().lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        options.append({"value": cleaned, "label": label or cleaned})

    add(recent_unit)
    add(native_unit)
    for value, label in GRAM_UNIT_OPTIONS:
        add(value, label)
    return options


def _food_image_url(food: Food) -> str | None:
    if food.image_data:
        return f"/foods/{food.id}/image"
    if food.image_url:
        return food.image_url
    return _source_payload_image_url(food.raw_source_payload)


def food_to_read(session: Session, food: Food) -> FoodRead:
    metadata = get_food_metadata(session, food)
    return FoodRead(
        id=food.id,
        canonical_name=food.canonical_name,
        brand=food.brand,
        source=food.source,
        source_food_id=food.source_food_id,
        image_url=_food_image_url(food),
        image_source_url=food.image_url or _source_payload_image_url(food.raw_source_payload),
        icon_key=food.icon_key,
        icon_symbol=food_icon_symbol(food.icon_key),
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
