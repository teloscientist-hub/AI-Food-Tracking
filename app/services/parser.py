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
    "container",
    "containers",
    "bottle",
    "bottles",
    "package",
    "packages",
    "can",
    "cans",
    "link",
    "links",
    "patty",
    "patties",
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
    "stick",
    "sticks",
}

NUMBER_WORDS = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
}

FILLER_TOKENS = {"of", "a", "an"}


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


def strip_leading_bullets(value: str) -> str:
    return re.sub(r"^\s*[-*•]+\s*", "", value).strip()


def parse_quantity(token: str) -> float | None:
    cleaned = token.strip().lower()
    if cleaned in NUMBER_WORDS:
        return NUMBER_WORDS[cleaned]
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
    cleaned = raw_text.replace("\r\n", "\n")
    parts = re.split(
        r",|\n|;|(?<=\s)-\s+|\band\b(?=\s+(?:\d+(?:\.\d+)?|\d+/\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an|my)\b)",
        cleaned,
        flags=re.IGNORECASE,
    )
    return [strip_leading_bullets(part) for part in parts if strip_leading_bullets(part)]


def clean_phrase_tokens(tokens: list[str]) -> list[str]:
    cleaned = tokens[:]
    while cleaned and cleaned[0].lower() in FILLER_TOKENS:
        cleaned = cleaned[1:]

    phrase = " ".join(cleaned)
    phrase = re.sub(r"\b\d+\s*count\b", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\bbrand\b", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\bwith\s+\d+(?:\.\d+)?\s*g\s+of\s+protein\b", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\bwith\s+\d+(?:\.\d+)?\s*grams?\s+of\s+protein\b", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\s+", " ", phrase).strip()
    return phrase.split()


def parse_food_phrase(segment: str) -> ParsedFoodItem:
    tokens = strip_leading_bullets(segment).split()
    if not tokens:
        return ParsedFoodItem(raw_text=segment, phrase="", quantity=1.0, unit=None, quantity_text=None)

    quantity = parse_quantity(tokens[0])
    unit: str | None = None
    start_idx = 0
    quantity_text: str | None = None
    if quantity is not None:
        quantity_text = tokens[0]
        start_idx = 1
        while start_idx < len(tokens) and tokens[start_idx].lower() in FILLER_TOKENS:
            start_idx += 1
        if start_idx < len(tokens):
            compound_match = re.match(r"^(\d+(?:\.\d+)?)[- ]?(g|gram|grams|oz|ounce|ounces|lb|lbs|cup|cups|tbsp|tsp)\b$", tokens[start_idx], flags=re.IGNORECASE)
            if compound_match:
                quantity = float(compound_match.group(1))
                unit = compound_match.group(2).lower()
                quantity_text = tokens[start_idx]
                start_idx += 1
                while start_idx < len(tokens) and tokens[start_idx].lower() in FILLER_TOKENS:
                    start_idx += 1
        if start_idx < len(tokens) and tokens[start_idx].lower() in KNOWN_UNITS:
            unit = tokens[start_idx].lower()
            start_idx += 1
            while start_idx < len(tokens) and tokens[start_idx].lower() in FILLER_TOKENS:
                start_idx += 1

    phrase_tokens = tokens[start_idx:] if start_idx < len(tokens) else tokens
    phrase_tokens = clean_phrase_tokens(phrase_tokens)
    phrase = " ".join(phrase_tokens).strip()
    if not phrase:
        phrase = strip_leading_bullets(segment)
    if quantity is None:
        quantity = 1.0

    return ParsedFoodItem(
        raw_text=strip_leading_bullets(segment),
        phrase=phrase,
        quantity=quantity,
        unit=unit,
        quantity_text=quantity_text,
    )


def parse_entry(raw_text: str) -> list[ParsedFoodItem]:
    return [parse_food_phrase(part) for part in split_entry(raw_text)]
