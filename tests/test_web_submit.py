from app.routers.web import _parse_selected_food_value, review_log_entry


def test_parse_selected_food_value_accepts_plain_numeric_food_ids() -> None:
    assert _parse_selected_food_value("5") == ("food", 5)


def test_parse_selected_food_value_accepts_prefixed_values() -> None:
    assert _parse_selected_food_value("food:12") == ("food", 12)
    assert _parse_selected_food_value("external:3") == ("external", 3)


def test_parse_selected_food_value_degrades_unknown_values_to_unresolved() -> None:
    assert _parse_selected_food_value("") == ("unresolved", None)
    assert _parse_selected_food_value("unresolved") == ("unresolved", None)
    assert _parse_selected_food_value("weird-value") == ("unresolved", None)


def test_blank_review_submission_redirects_back_with_error(session) -> None:
    response = review_log_entry(
        request=None,  # type: ignore[arg-type]
        raw_input_text="   ",
        meal_label="Breakfast",
        logged_at="2026-04-25T09:00",
        redirect_to="/log",
        session=session,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/log?")
    assert "error=" in location
