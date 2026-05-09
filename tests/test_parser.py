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


def test_parse_entry_preserves_food_names_with_and_inside_phrase() -> None:
    items = parse_entry("1.5 oz of Kirkland shredded cheddar and jack mix")

    assert len(items) == 1
    assert items[0].quantity == 1.5
    assert items[0].unit == "oz"
    assert items[0].phrase == "Kirkland shredded cheddar and jack mix"


def test_parse_entry_handles_spelled_numbers_and_phrase_cleanup() -> None:
    items = parse_entry(
        '- Five eggs - 1/32 of a stick of butter - 1 ratio Brand 25 g blueberry probiotic yogurt - 1 Reese\'s brand protein bar "One" with 18 g of protein'
    )

    assert len(items) == 4
    assert items[0].quantity == 5
    assert items[0].phrase == "eggs"
    assert items[1].quantity == 1 / 32
    assert items[1].unit == "stick"
    assert items[1].phrase == "butter"
    assert items[2].phrase == "ratio 25 g blueberry probiotic yogurt"
    assert items[3].phrase == "Reese's protein bar \"One\""


def test_parse_entry_handles_brand_phrase_and_compound_weight_token() -> None:
    items = parse_entry(
        "- Wilde Protein Chips 50 count\n- 2 containers of Dannon light and fit\n- 1 5-oz banana"
    )

    assert len(items) == 3
    assert items[0].quantity == 1.0
    assert items[0].phrase == "Wilde Protein Chips"
    assert items[1].quantity == 2.0
    assert items[1].unit == "containers"
    assert items[1].phrase == "Dannon light and fit"
    assert items[2].quantity == 5.0
    assert items[2].unit == "oz"
    assert items[2].phrase == "banana"
