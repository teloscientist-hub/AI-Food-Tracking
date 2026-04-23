from app.services.parser import parse_entry


def test_parse_entry_handles_quantities_units_and_brands() -> None:
    items = parse_entry("2 eggs, 3 bacon, 1 Fairlife 42, 1 tbsp butter")

    assert len(items) == 4
    assert items[0].quantity == 2
    assert items[0].phrase == "eggs"
    assert items[1].quantity == 3
    assert items[1].phrase == "bacon"
    assert items[2].quantity == 1
    assert items[2].phrase == "Fairlife 42"
    assert items[3].unit == "tbsp"
    assert items[3].phrase == "butter"


def test_parse_entry_defaults_to_single_serving_for_natural_language() -> None:
    items = parse_entry("protein coffee and my yogurt bowl")

    assert len(items) == 2
    assert items[0].quantity == 1.0
    assert items[0].phrase == "protein coffee"
    assert items[1].phrase == "my yogurt bowl"

