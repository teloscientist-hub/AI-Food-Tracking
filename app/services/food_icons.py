from __future__ import annotations


ICON_LIBRARY: list[dict[str, str]] = [
    {"key": "egg", "label": "Eggs", "symbol": "🥚"},
    {"key": "chicken", "label": "Chicken", "symbol": "🍗"},
    {"key": "steak", "label": "Steak", "symbol": "🥩"},
    {"key": "fish", "label": "Fish", "symbol": "🐟"},
    {"key": "bacon", "label": "Bacon", "symbol": "🥓"},
    {"key": "cheese", "label": "Cheese", "symbol": "🧀"},
    {"key": "butter", "label": "Butter", "symbol": "🧈"},
    {"key": "yogurt", "label": "Yogurt", "symbol": "🥣"},
    {"key": "shake", "label": "Shake", "symbol": "🥤"},
    {"key": "coffee", "label": "Coffee", "symbol": "☕"},
    {"key": "protein_bar", "label": "Protein Bar", "symbol": "🍫"},
    {"key": "banana", "label": "Banana", "symbol": "🍌"},
    {"key": "avocado", "label": "Avocado", "symbol": "🥑"},
    {"key": "berries", "label": "Berries", "symbol": "🫐"},
    {"key": "apple", "label": "Apple", "symbol": "🍎"},
    {"key": "salad", "label": "Salad", "symbol": "🥗"},
    {"key": "nuts", "label": "Nuts", "symbol": "🥜"},
    {"key": "bread", "label": "Bread", "symbol": "🍞"},
    {"key": "rice", "label": "Rice", "symbol": "🍚"},
    {"key": "soup", "label": "Soup", "symbol": "🍲"},
    {"key": "bowl", "label": "Bowl", "symbol": "🍜"},
    {"key": "drink", "label": "Drink", "symbol": "🧃"},
    {"key": "vegetable", "label": "Vegetable", "symbol": "🥕"},
    {"key": "meal", "label": "Meal", "symbol": "🍽️"},
]


ICON_MAP: dict[str, dict[str, str]] = {item["key"]: item for item in ICON_LIBRARY}


def food_icon_symbol(icon_key: str | None) -> str | None:
    if not icon_key:
        return None
    item = ICON_MAP.get(icon_key)
    return item["symbol"] if item else None
