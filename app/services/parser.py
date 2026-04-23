from __future__ import annotations

import re
from dataclasses import dataclass


KNOWN_UNITS = {
    "g",
    "gram",
    "grams",
    "oz",
    "ounce",
    "ounces",
    "lb",
    "lbs",
    "cup",
    "cups",
    "tbsp",
    "tsp",
    "slice",
    "slices",
    "serving",
    "servings",
    "piece",
    "pieces",
    "strip",
    "strips",
}


@dataclass(slots=True)
class ParsedFoodItem:
    raw_text: str
    phrase: str
    quantity: float
    unit: str | None
    quantity_text: str | None


def normalize_text(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def parse_quantity(token: str) -> float | None:
    cleaned = token.strip().lower()
    if cleaned in {"a", "an"}:
        return 1.0
    if "/" in cleaned:
        try:
            left, right = cleaned.split("/", 1)
            return float(left) / float(right)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def split_entry(raw_text: str) -> list[str]:
    parts = re.split(r",|\n|\band\b", raw_text)
    return [part.strip() for part in parts if part.strip()]


def parse_food_phrase(segment: str) -> ParsedFoodItem:
    tokens = segment.strip().split()
    if not tokens:
        return ParsedFoodItem(raw_text=segment, phrase="", quantity=1.0, unit=None, quantity_text=None)

    quantity = parse_quantity(tokens[0])
    unit: str | None = None
    start_idx = 0
    quantity_text: str | None = None
    if quantity is not None:
        quantity_text = tokens[0]
        start_idx = 1
        if len(tokens) > 1 and tokens[1].lower() in KNOWN_UNITS:
            unit = tokens[1].lower()
            start_idx = 2

    phrase_tokens = tokens[start_idx:] if start_idx < len(tokens) else tokens
    phrase = " ".join(phrase_tokens).strip()
    if not phrase:
        phrase = segment.strip()
    if quantity is None:
        quantity = 1.0

    return ParsedFoodItem(
        raw_text=segment.strip(),
        phrase=phrase,
        quantity=quantity,
        unit=unit,
        quantity_text=quantity_text,
    )


def parse_entry(raw_text: str) -> list[ParsedFoodItem]:
    return [parse_food_phrase(part) for part in split_entry(raw_text)]
