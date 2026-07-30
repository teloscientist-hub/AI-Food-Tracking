import io
import json
from datetime import UTC, date, datetime, timedelta

from app.models import MealEntry, MealEntryItem, HealthMeasurement
from app.routers.web import (
    _goal_ring_progress,
    _goal_ring_segments,
    _macro_pie_progress,
    _review_candidate_payload,
    _week_axis_for_metric,
)
from app.schemas.foods import FoodCreate
from app.services.food_service import create_food
from app.services.resolution import ResolutionCandidate
from app.services.usda_client import ExternalFoodCandidate


def test_main_pages_render_and_expose_primary_navigation(client) -> None:
    for path in ["/", "/log", "/foods", "/weekly", "/settings"]:
        response = client.get(path)
        assert response.status_code == 200

    home = client.get("/")
    body = home.text
    assert 'href="/foods"' in body
    assert 'href="/weekly"' in body
    assert 'href="/settings"' in body
    assert 'action="/log/review"' in body
    assert 'action="/dashboard/exercise"' in body
    assert 'name="weight_lb"' in body
    assert 'name="body_fat_pct"' in body


def test_parser_forms_show_submit_progress_state(client) -> None:
    for path in ["/", "/log"]:
        response = client.get(path)
        assert response.status_code == 200
        assert 'action="/log/review"' in response.text
        assert "data-loading-submit" in response.text
        assert 'data-loading-label="Parsing..."' in response.text
        assert "data-loading-status" in response.text
        assert "Parsing and matching foods..." in response.text


def test_review_page_keeps_parsed_weight_unit_independent_of_recent_picker_amount(client, session) -> None:
    chicken = create_food(
        session,
        FoodCreate(
            canonical_name="Chicken Breast",
            serving_description="1 breast",
            grams_per_serving=170,
            calories=280,
            protein_g=52,
            carbs_g=0,
            fat_g=6,
        ),
    )
    assert chicken.id

    response = client.post(
        "/log/review",
        data={
            "raw_input_text": "9 oz chicken breast",
            "meal_label": "Dinner",
            "logged_at": "2026-05-27T18:00",
            "redirect_to": "/log",
        },
    )

    assert response.status_code == 200
    assert 'value="9.0"' in response.text
    assert 'name="unit_0"' in response.text
    assert 'value="oz"' in response.text
    assert "data-preview-serving>1 oz</strong>" in response.text
    assert 'data-unit-input="0"' in response.text
    assert "grams_per_serving" in response.text
    assert "reviewServingLabel" in response.text
    assert "reviewMultiplier" in response.text


def test_settings_macro_summary_uses_net_carbs_calories(client) -> None:
    response = client.get("/settings")

    assert response.status_code == 200
    assert "Total carbs" not in response.text
    assert 'id="total_carbs_g"' not in response.text
    assert '<strong id="carb_cals">600' in response.text
    assert '<strong id="calculated_calories">2040' in response.text
    assert "net carbs x 5" in response.text


def test_health_endpoint_reports_ready(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "MML Food Tracking"}


def test_macro_pie_progress_uses_macro_calorie_ratio() -> None:
    assert _macro_pie_progress(protein_g=25, fat_g=50 / 9, net_carbs_g=10) == {
        "net_carbs_percent": 25.0,
        "protein_percent": 50.0,
        "fat_percent": 25.0,
        "net_carbs_stop": 25.0,
        "protein_stop": 75.0,
        "fat_stop": 100.0,
    }
    assert _macro_pie_progress(protein_g=0, fat_g=0, net_carbs_g=0) == {
        "net_carbs_percent": 0.0,
        "protein_percent": 0.0,
        "fat_percent": 0.0,
        "net_carbs_stop": 0.0,
        "protein_stop": 0.0,
        "fat_stop": 0.0,
    }


def test_dashboard_and_daily_log_render_uploaded_meal_item_images(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Nurri Protein Shake",
            serving_description="1 shake",
            grams_per_serving=330,
            calories=150,
            protein_g=30,
            carbs_g=2,
            fat_g=2,
            image_data=b"image-bytes",
            image_content_type="image/png",
        ),
    )
    entry = MealEntry(
        raw_input_text="nurri protein shake",
        meal_label="Breakfast",
        logged_at=datetime.combine(date.today(), datetime.min.time()),
    )
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=food.id,
            parsed_phrase="nurri protein shake",
            normalized_phrase="nurri protein shake",
            quantity=1,
            unit="shake",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=food.canonical_name,
            resolved_source=food.source,
            serving_description_snapshot=food.serving_description,
            grams_per_serving_snapshot=food.grams_per_serving,
            calories_snapshot=150,
            protein_g_snapshot=30,
            carbs_g_snapshot=2,
            fat_g_snapshot=2,
        )
    )
    session.commit()

    dashboard = client.get("/")
    daily = client.get(f"/daily/{date.today().isoformat()}")

    assert dashboard.status_code == 200
    assert daily.status_code == 200
    assert f'<img src="/foods/{food.id}/image" alt="Nurri Protein Shake">' in dashboard.text
    assert f'<img src="/foods/{food.id}/image" alt="Nurri Protein Shake">' in daily.text


def test_dashboard_macro_pie_uses_macro_calorie_ratio(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Macro Pie Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=200,
            protein_g=25,
            carbs_g=10,
            fat_g=50 / 9,
            net_carbs_g=10,
        ),
    )
    entry = MealEntry(
        raw_input_text="macro pie food",
        meal_label="Breakfast",
        logged_at=datetime.combine(date.today(), datetime.min.time()),
    )
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=food.id,
            parsed_phrase="macro pie food",
            normalized_phrase="macro pie food",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=food.canonical_name,
            resolved_source=food.source,
            calories_snapshot=200,
            protein_g_snapshot=25,
            carbs_g_snapshot=10,
            fat_g_snapshot=50 / 9,
            net_carbs_g_snapshot=10,
        )
    )
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "--macro-net-carbs-stop: 25.0%" in response.text
    assert "--macro-protein-stop: 75.0%" in response.text
    assert "--macro-fat-stop: 100.0%" in response.text
    assert "Net Carbs 25.0%, Protein 50.0%, Fat 25.0%" in response.text


def test_goal_ring_segments_darkens_toward_full_color() -> None:
    segments = _goal_ring_segments(100, "#efaaaa", "#df5a57", segment_count=4)

    assert segments[0] == {"start": 0.0, "length": 25.0, "color": "#eb9695"}
    assert segments[-1] == {"start": 75.0, "length": 25.0, "color": "#df5a57"}


def test_goal_ring_progress_tracks_second_clockwise_lap() -> None:
    assert _goal_ring_progress(75, 100) == {
        "base_percent": 75.0,
        "over_percent": 0.0,
        "total_percent": 75.0,
    }
    assert _goal_ring_progress(125, 100) == {
        "base_percent": 100.0,
        "over_percent": 25.0,
        "total_percent": 125.0,
    }
    assert _goal_ring_progress(225, 100) == {
        "base_percent": 100.0,
        "over_percent": 100.0,
        "total_percent": 225.0,
    }


def test_dashboard_goal_rings_render_layered_progress_variables(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "goal-ring-svg" in response.text
    assert "goal-ring-track" in response.text
    assert "goal-ring-layer" in response.text
    assert 'pathLength="100"' in response.text


def test_week_axis_exposes_goal_line_metadata() -> None:
    daily = {
        "calories": {"target": 2000},
        "protein": {"target": 180},
        "carbs": {"target": 150},
        "fat": {"target": 80},
        "fiber": {"target": 30},
        "net_carbs": {"target": 40},
    }
    weekly = {"days": [{"calories": value} for value in [0, 1200, 1800, 2100, 2400, 1500, 1900]]}

    axis = _week_axis_for_metric("calories", daily, weekly, "calories")

    assert axis["max"] == 4000.0
    assert axis["target"] == 2000.0
    assert axis["target_percent"] == 50.0
    assert axis["target_label"] == "2,000 goal"


def test_dashboard_week_chart_renders_goal_line_and_overage_segments(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Goal Line Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=2500,
            protein_g=25,
            carbs_g=10,
            fat_g=8,
            net_carbs_g=10,
        ),
    )
    entry = MealEntry(
        raw_input_text="goal line food",
        meal_label="Breakfast",
        logged_at=datetime.combine(date.today(), datetime.min.time()),
    )
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=food.id,
            parsed_phrase="goal line food",
            normalized_phrase="goal line food",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=food.canonical_name,
            resolved_source=food.source,
            calories_snapshot=2500,
            protein_g_snapshot=25,
            carbs_g_snapshot=10,
            fat_g_snapshot=8,
            net_carbs_g_snapshot=10,
        )
    )
    session.commit()

    response = client.get("/?metric=calories")

    assert response.status_code == 200
    assert 'class="week-chart metric-calories"' in response.text
    assert 'class="week-goal-line"' in response.text
    assert "2,200 goal" in response.text
    assert 'title="Today: 2500.0 calories"' in response.text
    assert "week-bar week-bar-total has-value" in response.text
    assert "week-bar week-bar-over has-value" in response.text
    assert "week-bar-value" in response.text
    assert "2,500" in response.text


def test_dashboard_week_chart_marks_yesterday_when_today_is_selected(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Yesterday Chart Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=4,
            net_carbs_g=5,
        ),
    )
    entry = MealEntry(
        raw_input_text="yesterday chart food",
        meal_label="Breakfast",
        logged_at=datetime.combine(date.today() - timedelta(days=1), datetime.min.time()),
    )
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=food.id,
            parsed_phrase="yesterday chart food",
            normalized_phrase="yesterday chart food",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=food.canonical_name,
            resolved_source=food.source,
            calories_snapshot=100,
            protein_g_snapshot=10,
            carbs_g_snapshot=5,
            fat_g_snapshot=4,
            net_carbs_g_snapshot=5,
        )
    )
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert 'title="Yesterday: 100.0 calories"' in response.text
    assert 'week-bar week-bar-total has-value is-yesterday' in response.text
    assert 'week-day is-yesterday' in response.text
    assert '>Y</span>' in response.text
    assert 'title="Today: 0 calories"' in response.text



def test_log_picker_add_preserves_current_page_order_until_fresh_visit(client, session) -> None:
    foods = [
        create_food(
            session,
            FoodCreate(
                canonical_name=name,
                serving_description="1 serving",
                grams_per_serving=1,
                calories=100,
                protein_g=10,
                carbs_g=5,
                fat_g=3,
            ),
        )
        for name in ["Route Stable Alpha", "Route Stable Beta", "Route Stable Gamma"]
    ]
    initial = client.get("/log")
    assert initial.status_code == 200
    marker = 'name="picker_order" value="'
    order_start = initial.text.index(marker) + len(marker)
    order_end = initial.text.index('"', order_start)
    picker_order = initial.text[order_start:order_end]
    first_name = next(food.canonical_name for food in foods if str(food.id) == picker_order.split(",")[0])
    logged_food = next(food for food in foods if str(food.id) == picker_order.split(",")[-1])

    add_response = client.post(
        "/log/picker/add",
        data={
            "food_id": str(logged_food.id),
            "quantity": "1",
            "unit": "serving",
            "meal_label": "Breakfast",
            "logged_at": datetime.now().isoformat(timespec="minutes"),
            "q": "",
            "source": "all",
            "picker_order": picker_order,
            "picker_scroll_y": "640",
            "redirect_to": "/log",
        },
        follow_redirects=False,
    )
    assert add_response.status_code == 303
    assert "picker_order=" in add_response.headers["location"]
    assert "picker_scroll_y=640" in add_response.headers["location"]

    stable_page = client.get(add_response.headers["location"])
    assert 'name="picker_scroll_y" value="640"' in stable_page.text
    fresh_page = client.get("/log")

    assert stable_page.text.index(f'aria-label="Add {first_name}"') < stable_page.text.index(f'aria-label="Add {logged_food.canonical_name}"')
    assert fresh_page.text.index(f'aria-label="Add {logged_food.canonical_name}"') < fresh_page.text.index(f'aria-label="Add {first_name}"')


def test_daily_log_submit_moves_food_to_top_on_fresh_picker_visit(client, session) -> None:
    older = create_food(
        session,
        FoodCreate(
            canonical_name="Alpha Earlier Daily Log Snack",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=3,
        ),
    )
    recent = create_food(
        session,
        FoodCreate(
            canonical_name="Zulu Protein Drink Added From Daily Log",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
        ),
    )
    food_created_at = datetime(2026, 5, 1, 8, 0)
    for food in [older, recent]:
        food.created_at = food_created_at
        food.updated_at = food_created_at

    shared_logged_at = datetime(2026, 5, 25, 12, 0)
    older_used_at = datetime(2026, 5, 25, 18, 0)
    older_entry = MealEntry(
        raw_input_text="older snack",
        meal_label="Snack 1",
        logged_at=shared_logged_at,
        created_at=older_used_at,
    )
    session.add(older_entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=older_entry.id,
            food_id=older.id,
            parsed_phrase=older.canonical_name,
            normalized_phrase=older.normalized_name,
            quantity=1.0,
            unit="serving",
            created_at=older_used_at,
        )
    )
    session.commit()

    submit_response = client.post(
        "/log/submit",
        data={
            "raw_input_text": "protein drink",
            "meal_label": "Snack 1",
            "logged_at": shared_logged_at.isoformat(timespec="minutes"),
            "item_count": "1",
            "candidate_json": json.dumps([[]]),
            "parsed_phrase_0": recent.canonical_name,
            "quantity_0": "1",
            "unit_0": "serving",
            "quantity_text_0": "1",
            "selected_food_id_0": f"food:{recent.id}",
        },
        follow_redirects=False,
    )
    assert submit_response.status_code == 303

    for path in ["/log", "/log/picker", "/log?q=daily+log&source=all", "/log/picker?q=daily+log&source=all"]:
        fresh_page = client.get(path)

        assert fresh_page.status_code == 200
        recent_position = fresh_page.text.index(f'aria-label="Add {recent.canonical_name}"')
        older_position = fresh_page.text.index(f'aria-label="Add {older.canonical_name}"')
        assert recent_position < older_position


def test_log_picker_renders_native_serving_quantity_for_count_units(client, session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="MML Roasted Asparagus",
            serving_description="10 spears",
            grams_per_serving=1,
            calories=110,
            protein_g=3.5,
            carbs_g=6,
            fat_g=0.5,
        ),
    )

    response = client.get("/log?q=asparagus&source=custom")

    assert response.status_code == 200
    assert 'data-native-serving-quantity="10.0"' in response.text
    assert 'data-native-unit="spears"' in response.text
    assert 'name="quantity" value="10.0"' in response.text
    assert '<option value="spears" selected>spears</option>' in response.text


def test_log_picker_renders_native_serving_quantity_for_leading_decimal_units(client, session) -> None:
    create_food(
        session,
        FoodCreate(
            canonical_name="Salad Creamy Italian",
            serving_description=".33 bag",
            grams_per_serving=1,
            calories=150,
            protein_g=3,
            carbs_g=8,
            fat_g=12,
        ),
    )

    response = client.get("/log?q=salad+creamy+italian&source=custom")

    assert response.status_code == 200
    assert 'data-native-serving-quantity="0.33"' in response.text
    assert 'data-native-unit="bag"' in response.text
    assert 'name="quantity" value="0.33"' in response.text
    assert '<option value="bag" selected>bag</option>' in response.text


def _picker_quantity_value_for_food(body: str, food_id: int) -> str:
    form_start = body.index(f'name="food_id" value="{food_id}"')
    marker = 'name="quantity" value="'
    value_start = body.index(marker, form_start) + len(marker)
    value_end = body.index('"', value_start)
    return body[value_start:value_end]


def test_log_picker_plus_keeps_submitted_quantity_after_merge(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Repeat Plus Shake",
            serving_description="1 serving",
            grams_per_serving=50,
            calories=100,
            protein_g=10,
            carbs_g=3,
            fat_g=2,
            fiber_g=1,
            net_carbs_g=2,
        ),
    )
    logged_at = datetime(2026, 5, 12, 8, 0).isoformat(timespec="minutes")

    page = client.get("/log?q=Repeat+Plus&source=custom")
    assert _picker_quantity_value_for_food(page.text, food.id) == "1.0"

    for expected_quantity in [1.0, 2.0, 3.0]:
        response = client.post(
            "/log/picker/add",
            data={
                "food_id": str(food.id),
                "quantity": _picker_quantity_value_for_food(page.text, food.id),
                "unit": "serving",
                "meal_label": "Breakfast",
                "logged_at": logged_at,
                "q": "Repeat Plus",
                "source": "custom",
                "redirect_to": "/log",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get(response.headers["location"])
        assert _picker_quantity_value_for_food(page.text, food.id) == "1.0"
        item = session.query(MealEntryItem).filter_by(food_id=food.id, unit="serving").one()
        assert item.quantity == expected_quantity

    fresh_page = client.get("/log?q=Repeat+Plus&source=custom")
    assert _picker_quantity_value_for_food(fresh_page.text, food.id) == "1.0"


def test_log_picker_add_merges_same_food_and_unit(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Mergeable Picker Shake",
            serving_description="1 serving",
            grams_per_serving=50,
            calories=100,
            protein_g=10,
            carbs_g=3,
            fat_g=2,
            fiber_g=1,
            net_carbs_g=2,
        ),
    )
    logged_at = datetime(2026, 5, 12, 8, 0).isoformat(timespec="minutes")

    for quantity in ["1", "1", "3"]:
        response = client.post(
            "/log/picker/add",
            data={
                "food_id": str(food.id),
                "quantity": quantity,
                "unit": "serving",
                "meal_label": "Breakfast",
                "logged_at": logged_at,
                "redirect_to": "/log",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    items = session.query(MealEntryItem).all()
    assert len(items) == 1
    item = items[0]
    assert item.quantity == 5.0
    assert item.unit == "serving"
    assert item.quantity_text == "3"
    assert item.calories_snapshot == 500.0
    assert item.protein_g_snapshot == 50.0
    assert item.net_carbs_g_snapshot == 10.0

    response = client.post(
        "/log/picker/add",
        data={
            "food_id": str(food.id),
            "quantity": "2",
            "unit": "oz",
            "meal_label": "Breakfast",
            "logged_at": logged_at,
            "redirect_to": "/log",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert session.query(MealEntryItem).count() == 2
    serving_item = session.query(MealEntryItem).filter_by(food_id=food.id, unit="serving").one()
    ounce_item = session.query(MealEntryItem).filter_by(food_id=food.id, unit="oz").one()
    assert serving_item.quantity == 5.0
    assert ounce_item.quantity == 2.0


def test_dashboard_and_log_buttons_point_to_live_endpoints(client) -> None:
    dashboard = client.get("/")
    body = dashboard.text
    for meal in ["Breakfast", "Lunch", "Dinner", "Snack 1", "Snack 2", "Snack 3"]:
        assert f'meal_label={meal.replace(" ", "%20")}' in body or f'meal_label={meal}' in body
        assert "logged_at=" in body

    foods = client.get("/foods")
    foods_body = foods.text
    assert 'href="/foods/custom/new"' in foods_body


def test_dashboard_date_arrows_navigate_previous_and_next_days(client) -> None:
    target_day = date.today() + timedelta(days=2)
    response = client.get(f"/?target_date={target_day.isoformat()}&metric=protein")
    assert response.status_code == 200
    assert target_day.isoformat() in response.text
    assert f'href="/?target_date={(target_day - timedelta(days=1)).isoformat()}&amp;metric=protein"' in response.text
    assert f'href="/?target_date={(target_day + timedelta(days=1)).isoformat()}&amp;metric=protein"' in response.text


def test_daily_log_date_controls_navigate_previous_and_next_days(client) -> None:
    target_day = date.today() + timedelta(days=2)

    redirect = client.get(f"/daily?target_date={target_day.isoformat()}", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == f"/daily/{target_day.isoformat()}"

    response = client.get(f"/daily/{target_day.isoformat()}")

    assert response.status_code == 200
    assert f'href="/daily/{(target_day - timedelta(days=1)).isoformat()}"' in response.text
    assert f'href="/daily/{(target_day + timedelta(days=1)).isoformat()}"' in response.text
    assert 'action="/daily"' in response.text
    assert 'name="target_date"' in response.text
    assert f'value="{target_day.isoformat()}"' in response.text
    assert f'href="/log?target_date={target_day.isoformat()}"' in response.text


def test_add_log_date_controls_navigate_previous_and_next_days(client) -> None:
    target_day = date.today() + timedelta(days=2)
    response = client.get(f"/log?target_date={target_day.isoformat()}&meal_label=Lunch&source=all&q=egg")

    assert response.status_code == 200
    assert f'href="/log?target_date={(target_day - timedelta(days=1)).isoformat()}&amp;meal_label=Lunch&amp;source=all&amp;q=egg"' in response.text
    assert f'href="/log?target_date={(target_day + timedelta(days=1)).isoformat()}&amp;meal_label=Lunch&amp;source=all&amp;q=egg"' in response.text
    assert 'action="/log"' in response.text
    assert f'value="{target_day.isoformat()}"' in response.text
    assert f'value="{target_day.isoformat()}T' in response.text


def test_shared_layout_preserves_scroll_after_page_actions(client) -> None:
    response = client.get(f"/daily/{date.today().isoformat()}")

    assert response.status_code == 200
    assert "mml-food-tracking:scroll-restore" in response.text
    assert "const rememberFormScroll" in response.text
    assert 'document.querySelectorAll("form")' in response.text
    assert 'form.addEventListener("submit", () => rememberFormScroll(form))' in response.text
    assert 'input[name="redirect_to"]' in response.text
    assert "restorePageScroll();" in response.text
    assert "rememberFormScroll(mealMoveForm);" in response.text
    assert 'document.querySelectorAll("form[data-loading-submit]")' in response.text
    assert 'form.classList.add("is-submitting")' in response.text
    assert "submitButton.disabled = true;" in response.text
    assert 'quantityInput?.addEventListener("keydown", (event) => {' in response.text
    assert 'event.key !== "Enter"' in response.text
    assert "event.stopPropagation();" in response.text
    assert "quantityInput.blur();" in response.text

    foods = client.get("/foods")
    assert foods.status_code == 200
    assert "mml-food-tracking:scroll-restore" in foods.text


def test_dashboard_week_panel_renders_goal_based_axis_labels(client) -> None:
    response = client.get("/?metric=calories")
    assert response.status_code == 200
    assert 'class="week-axis"' in response.text
    assert ">500<" in response.text
    assert ">1000<" in response.text


def test_review_candidate_payload_strips_large_raw_source_payload() -> None:
    candidate = ResolutionCandidate(
        food_id=None,
        canonical_name="Pure Protein Shake",
        brand="Pure Protein",
        source="openfoodfacts",
        confidence=0.94,
        strategy="off_search",
        serving_description="1 bottle",
        grams_per_serving=325.0,
        calories=140.0,
        protein_g=30.0,
        carbs_g=6.0,
        fat_g=2.0,
        fiber_g=4.0,
        net_carbs_g=2.0,
        raw_payload={
            "source_food_id": "pp-shake-1",
            "raw_source_payload": {
                "code": "pp-shake-1",
                "product_name": "Pure Protein Shake",
                "image_front_url": "https://example.com/shake.png",
                "large_unused_field": "x" * (1024 * 1024),
            },
        },
    )

    payload = _review_candidate_payload(candidate)
    serialized = json.dumps(payload)

    assert len(serialized) < 4096
    assert payload["source_food_id"] == "pp-shake-1"
    assert payload["image_url"] == "https://example.com/shake.png"
    assert payload["raw_payload"] == {
        "code": "pp-shake-1",
        "product_name": "Pure Protein Shake",
        "image_front_url": "https://example.com/shake.png",
    }
    assert "large_unused_field" not in serialized


def test_food_library_custom_source_shows_local_catalog_only(client, session) -> None:
    create_food(
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
    create_food(
        session,
        FoodCreate(
            canonical_name="Avocado",
            serving_description="100 g",
            grams_per_serving=100,
            calories=160,
            protein_g=2,
            carbs_g=9,
            fat_g=15,
            source="usda",
            source_food_id="usda-1",
        ),
    )
    create_food(
        session,
        FoodCreate(
            canonical_name="Premier Protein Cafe Latte",
            brand="Premier Protein",
            serving_description="1 bottle",
            grams_per_serving=325,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
            source="openfoodfacts",
            source_food_id="off-1",
        ),
    )

    custom_page = client.get("/foods?source=custom")
    usda_page = client.get("/foods?source=usda")
    off_page = client.get("/foods?source=openfoodfacts")

    assert "Protein Coffee" in custom_page.text
    assert "Avocado" not in custom_page.text
    assert "Premier Protein Cafe Latte" not in custom_page.text

    assert "Enter a search term above and press Enter to search usda." in usda_page.text
    assert "Avocado" not in usda_page.text
    assert "Premier Protein Cafe Latte" not in usda_page.text

    assert "Enter a search term above and press Enter to search openfoodfacts." in off_page.text
    assert "Protein Coffee" not in off_page.text
    assert "Avocado" not in off_page.text


def test_foods_library_usda_query_uses_external_api_results(client, monkeypatch) -> None:
    candidate = ExternalFoodCandidate(
        canonical_name="USDA Avocado",
        brand=None,
        source="usda",
        source_food_id="usda-123",
        serving_description="1 avocado",
        grams_per_serving=150.0,
        calories=240.0,
        protein_g=3.0,
        carbs_g=12.0,
        fat_g=22.0,
        fiber_g=10.0,
        net_carbs_g=2.0,
        raw_source_payload={"description": "USDA Avocado"},
        score=0.91,
    )

    monkeypatch.setattr("app.routers.web.USDAClient.search", lambda self, phrase, limit=12: [candidate])

    response = client.get("/foods?source=usda&q=avocado")
    assert response.status_code == 200
    assert "USDA Avocado" in response.text
    assert "Save and add" in response.text
    assert "Save and edit" in response.text
    assert 'action="/foods/external/save"' in response.text


def test_foods_library_openfoodfacts_query_uses_external_api_results(client, monkeypatch) -> None:
    candidate = ExternalFoodCandidate(
        canonical_name="Premier Protein Cafe Latte",
        brand="Premier Protein",
        source="openfoodfacts",
        source_food_id="off-123",
        serving_description="1 bottle",
        grams_per_serving=325.0,
        calories=160.0,
        protein_g=30.0,
        carbs_g=5.0,
        fat_g=3.0,
        fiber_g=0.0,
        net_carbs_g=5.0,
        raw_source_payload={"product_name": "Premier Protein Cafe Latte"},
        score=0.94,
    )

    monkeypatch.setattr("app.routers.web.OpenFoodFactsClient.search", lambda self, phrase, limit=12: [candidate])

    response = client.get("/foods?source=openfoodfacts&q=premier")
    assert response.status_code == 200
    assert "Premier Protein Cafe Latte" in response.text
    assert "Save and add" in response.text
    assert "Save and edit" in response.text


def test_foods_library_external_save_actions_create_custom_food_and_redirect(client, session) -> None:
    candidate = {
        "canonical_name": "Quest Nacho Chips",
        "brand": "Quest",
        "source": "openfoodfacts",
        "source_food_id": "quest-1",
        "serving_description": "1 bag",
        "grams_per_serving": 32.0,
        "calories": 140.0,
        "protein_g": 18.0,
        "carbs_g": 5.0,
        "fat_g": 6.0,
        "fiber_g": 1.0,
        "net_carbs_g": 4.0,
        "raw_payload": {"product_name": "Quest Nacho Chips"},
    }

    save_response = client.post(
        "/foods/external/save",
        data={"candidate_json": json.dumps(candidate), "action": "save", "source": "openfoodfacts", "q": "quest"},
        follow_redirects=False,
    )
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/foods?source=custom&q=Quest+Nacho+Chips"

    save_add_response = client.post(
        "/foods/external/save",
        data={"candidate_json": json.dumps(candidate), "action": "save_add", "source": "openfoodfacts", "q": "quest"},
        follow_redirects=False,
    )
    assert save_add_response.status_code == 303
    assert save_add_response.headers["location"].startswith("/foods/")
    assert "/edit" not in save_add_response.headers["location"]

    save_edit_response = client.post(
        "/foods/external/save",
        data={"candidate_json": json.dumps(candidate), "action": "save_edit", "source": "openfoodfacts", "q": "quest"},
        follow_redirects=False,
    )
    assert save_edit_response.status_code == 303
    assert save_edit_response.headers["location"].endswith("/edit")


def test_food_library_previously_logged_sort_chip_submits_real_sort(client, session) -> None:
    create_food(
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

    response = client.get("/foods?source=custom&sort=previously_logged")
    assert response.status_code == 200
    assert 'name="sort" value="previously_logged"' in response.text
    assert 'chip active' in response.text


def test_food_library_buttons_work_for_custom_and_external_foods(client, session) -> None:
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
    external = create_food(
        session,
        FoodCreate(
            canonical_name="Premier Protein Cafe Latte",
            brand="Premier Protein",
            serving_description="1 bottle",
            grams_per_serving=325,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
            source="openfoodfacts",
            source_food_id="premier-123",
        ),
    )

    page = client.get("/foods?source=custom")
    assert page.status_code == 200
    assert f'href="/foods/{custom.id}/edit"' in page.text

    duplicate_response = client.post(f"/foods/{external.id}/duplicate", follow_redirects=False)
    assert duplicate_response.status_code == 303


def test_custom_food_create_update_and_image_endpoint_work(client, session) -> None:
    create_response = client.post(
        "/foods/custom/save",
        data={
            "canonical_name": "Nurri Protein Shake",
            "brand": "Nurri",
            "serving_description": "1 serving",
            "grams_per_serving": "330",
            "calories": "150",
            "protein_g": "30",
            "carbs_g": "2",
            "fat_g": "3",
            "fiber_g": "0",
            "net_carbs_g": "2",
            "aliases": "nurri shake, nurri",
            "notes": "custom import",
        },
        files={"image_upload": ("nurri.png", io.BytesIO(b"png-bytes"), "image/png")},
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    foods_page = client.get("/foods?source=custom")
    assert "Nurri Protein Shake" in foods_page.text

    from app.models import Food

    created = session.query(Food).filter(Food.canonical_name == "Nurri Protein Shake", Food.is_current.is_(True)).one()
    image_response = client.get(f"/foods/{created.id}/image")
    assert image_response.status_code == 200
    assert image_response.content == b"png-bytes"
    assert image_response.headers["content-type"].startswith("image/png")

    update_response = client.post(
        f"/foods/{created.id}/save",
        data={
            "canonical_name": "Nurri Protein Shake",
            "brand": "Nurri",
            "serving_description": "1 bottle",
            "grams_per_serving": "330",
            "calories": "160",
            "protein_g": "30",
            "carbs_g": "3",
            "fat_g": "3",
            "fiber_g": "0",
            "net_carbs_g": "3",
            "aliases": "nurri shake, nurri",
            "notes": "updated custom import",
        },
        files={"image_upload": ("nurri-new.jpg", io.BytesIO(b"jpeg-bytes"), "image/jpeg")},
        follow_redirects=False,
    )
    assert update_response.status_code == 303

    updated = session.query(Food).filter(Food.canonical_name == "Nurri Protein Shake", Food.is_current.is_(True)).one()
    assert updated.id != created.id
    updated_image_response = client.get(f"/foods/{updated.id}/image")
    assert updated_image_response.status_code == 200
    assert updated_image_response.content == b"jpeg-bytes"
    assert updated_image_response.headers["content-type"].startswith("image/jpeg")


def test_food_detail_exposes_edit_and_duplicate_actions(client, session) -> None:
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
    external = create_food(
        session,
        FoodCreate(
            canonical_name="Premier Protein Cafe Latte",
            brand="Premier Protein",
            serving_description="1 bottle",
            grams_per_serving=325,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
            source="openfoodfacts",
            source_food_id="premier-123",
        ),
    )

    custom_page = client.get(f"/foods/{custom.id}")
    external_page = client.get(f"/foods/{external.id}")

    assert custom_page.status_code == 200
    assert external_page.status_code == 200
    assert f'action="/foods/{custom.id}/edit-copy"' in custom_page.text
    assert f'action="/foods/{custom.id}/duplicate"' in custom_page.text
    assert f'action="/foods/{custom.id}/remove"' in custom_page.text
    assert f'action="/foods/{external.id}/edit-copy"' in external_page.text
    assert f'action="/foods/{external.id}/duplicate"' in external_page.text
    assert f'action="/foods/{external.id}/remove"' not in external_page.text

    edit_response = client.post(f"/foods/{external.id}/edit-copy", follow_redirects=False)
    assert edit_response.status_code == 303
    assert "/edit" in edit_response.headers["location"]

    remove_response = client.post(f"/foods/{custom.id}/remove", follow_redirects=False)
    assert remove_response.status_code == 303
    assert remove_response.headers["location"] == "/foods?source=custom"


def test_custom_food_editor_exposes_image_adjustment_controls(client) -> None:
    response = client.get("/foods/custom/new")

    assert response.status_code == 200
    assert 'id="custom-food-image-upload"' in response.text
    assert 'data-image-crop-canvas' in response.text
    assert 'data-image-rotate-left' in response.text
    assert 'data-image-rotate-right' in response.text
    assert 'data-image-zoom' in response.text
    assert 'imageOrientation: "from-image"' in response.text
    assert '<button class="button ghost" type="button" data-edit-current-image' not in response.text


def test_custom_food_editor_can_edit_existing_image(client, session) -> None:
    custom = create_food(
        session,
        FoodCreate(
            canonical_name="Image Edit Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=4,
            image_data=b"image-bytes",
            image_content_type="image/png",
        ),
    )

    response = client.get(f"/foods/{custom.id}/edit")

    assert response.status_code == 200
    assert 'data-edit-current-image' in response.text
    assert f'data-current-image-url="/foods/{custom.id}/image"' in response.text
    assert 'data-current-image-name="Image Edit Food"' in response.text


def test_custom_food_editor_exposes_delete_action_for_custom_food(client, session) -> None:
    custom = create_food(
        session,
        FoodCreate(
            canonical_name="Delete Me Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=4,
        ),
    )

    response = client.get(f"/foods/{custom.id}/edit")
    assert response.status_code == 200
    assert f'action="/foods/{custom.id}/remove"' in response.text

    removed_page = client.get(f"/foods/{custom.id}")
    assert removed_page.status_code == 200
    custom_library_page = client.get("/foods?source=custom")
    assert "Protein Coffee" not in custom_library_page.text


def test_review_can_save_selected_external_match_as_custom_food(client, session) -> None:
    external = create_food(
        session,
        FoodCreate(
            canonical_name="Premier Protein Cafe Latte",
            brand="Premier Protein",
            serving_description="1 bottle",
            grams_per_serving=325,
            calories=160,
            protein_g=30,
            carbs_g=5,
            fat_g=3,
            source="openfoodfacts",
            source_food_id="premier-123",
        ),
    )

    response = client.post(
        "/log/save-custom",
        data={
            "raw_input_text": "1 premier protein cafe latte",
            "meal_label": "Breakfast",
            "logged_at": "",
            "item_count": "1",
            "candidate_json": "[]",
            "save_custom_index": "0",
            "parsed_phrase_0": "premier protein cafe latte",
            "selected_food_id_0": f"food:{external.id}",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/edit")

    custom_page = client.get("/foods?source=custom")
    assert "Premier Protein Cafe Latte" in custom_page.text


def test_review_can_save_selected_external_candidate_as_custom_food(client) -> None:
    candidate_json = json.dumps(
        [
            [
                {
                    "food_id": None,
                    "canonical_name": "Pure Protein Cafe Latte",
                    "brand": "Pure Protein",
                    "source": "openfoodfacts",
                    "confidence": 0.92,
                    "strategy": "off_search",
                    "serving_description": "1 bottle",
                    "calories": 170.0,
                    "protein_g": 30.0,
                    "carbs_g": 6.0,
                    "fat_g": 3.0,
                    "fiber_g": 1.0,
                    "net_carbs_g": 5.0,
                    "grams_per_serving": 330.0,
                    "source_food_id": "off-pp-1",
                    "raw_payload": {"code": "off-pp-1"},
                }
            ]
        ]
    )

    response = client.post(
        "/log/save-custom",
        data={
            "raw_input_text": "1 pure protein cafe latte",
            "meal_label": "Breakfast",
            "logged_at": "",
            "item_count": "1",
            "candidate_json": candidate_json,
            "save_custom_index": "0",
            "parsed_phrase_0": "pure protein cafe latte",
            "selected_food_id_0": "external:0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/edit")

    custom_page = client.get("/foods?source=custom")
    assert "Pure Protein Cafe Latte" in custom_page.text


def test_api_endpoints_support_basic_workflows(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Egg",
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
            aliases=["egg"],
        ),
    )

    daily = client.get("/api/summaries/daily")
    weekly = client.get("/api/summaries/weekly")
    unresolved = client.get("/api/unresolved")
    search = client.get("/api/foods/search?q=egg")
    log_response = client.post(
        "/api/logs",
        json={
            "raw_input_text": "2 eggs",
            "meal_label": "Breakfast",
            "logged_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "parsed_phrase": "eggs",
                    "quantity": 2,
                    "unit": None,
                    "quantity_text": None,
                    "selected_food_id": food.id,
                    "always_map": False,
                }
            ],
        },
    )
    resolve = client.post("/api/resolve", json={"phrase": "1 egg"})

    assert daily.status_code == 200
    assert weekly.status_code == 200
    assert unresolved.status_code == 200
    assert search.status_code == 200
    assert log_response.status_code == 200
    assert resolve.status_code == 200
    assert search.json()["foods"][0]["canonical_name"] == "Egg"
    assert "meal_entry_id" in log_response.json()
    assert resolve.json()["items"]


def test_meal_item_actions_render_and_work(client, session) -> None:
    food = create_food(
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
    meal_entry = MealEntry(raw_input_text="2 eggs", meal_label="Breakfast", logged_at=datetime.now(UTC))
    session.add(meal_entry)
    session.flush()
    meal_item = MealEntryItem(
        meal_entry_id=meal_entry.id,
        food_id=food.id,
        parsed_phrase="eggs",
        normalized_phrase="eggs",
        quantity=2.0,
        unit="egg",
        quantity_text="2",
        resolved_food_name="Egg",
        resolved_source="custom",
        serving_description_snapshot="1 egg",
        grams_per_serving_snapshot=100.0,
        calories_snapshot=144.0,
        protein_g_snapshot=12.0,
        carbs_g_snapshot=0.8,
        fat_g_snapshot=10.0,
    )
    session.add(meal_item)
    session.commit()

    daily_page = client.get(f"/daily/{meal_entry.logged_at.date().isoformat()}")
    assert daily_page.status_code == 200
    assert f'/meal-items/{meal_item.id}/edit?redirect_to=/daily/{meal_entry.logged_at.date().isoformat()}' in daily_page.text
    assert f'action="/meal-items/{meal_item.id}/copy"' in daily_page.text
    assert f'action="/meal-items/{meal_item.id}/delete"' in daily_page.text

    edit_page = client.get(f"/meal-items/{meal_item.id}/edit?redirect_to=/")
    assert edit_page.status_code == 200
    assert "Edit Logged Item" in edit_page.text

    save_response = client.post(
        f"/meal-items/{meal_item.id}/save",
        data={
            "quantity": "3",
            "unit": "egg",
            "meal_label": "Lunch",
            "logged_at": meal_entry.logged_at.isoformat(timespec="minutes"),
            "redirect_to": "/",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/"
    session.refresh(meal_item)
    session.refresh(meal_entry)
    assert meal_item.quantity == 3.0
    assert meal_item.calories_snapshot == 216.0
    assert meal_entry.meal_label == "Lunch"

    copy_response = client.post(
        f"/meal-items/{meal_item.id}/copy",
        data={"redirect_to": "/"},
        follow_redirects=False,
    )
    assert copy_response.status_code == 303
    assert copy_response.headers["location"] == "/"
    assert session.query(MealEntryItem).filter(MealEntryItem.meal_entry_id == meal_entry.id).count() == 2

    latest_item = session.query(MealEntryItem).order_by(MealEntryItem.id.desc()).first()
    assert latest_item is not None
    delete_response = client.post(
        f"/meal-items/{latest_item.id}/delete",
        data={"redirect_to": "/"},
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/"
    assert session.query(MealEntryItem).filter(MealEntryItem.meal_entry_id == meal_entry.id).count() == 1


def test_dashboard_exercise_save_supports_zone2_minutes(client, session) -> None:
    response = client.post(
        "/dashboard/exercise",
        data={
            "checkin_date": datetime.now(UTC).date().isoformat(),
            "zone2_minutes": "42",
            "zone4_minutes": "12",
            "did_push_workout": "1",
            "weight_lb": "211.6",
            "body_fat_pct": "27.4",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    from app.models import ExerciseCheckIn

    checkin = session.query(ExerciseCheckIn).one()
    assert checkin.did_zone2 is True
    assert checkin.zone2_minutes == 42
    assert checkin.zone4_minutes == 12
    assert checkin.did_push_workout is True
    assert checkin.did_pull_workout is False

    measurement = session.query(HealthMeasurement).one()
    assert measurement.weight_lb == 211.6
    assert measurement.body_fat_pct == 27.4


def test_review_submit_can_exclude_an_item_from_meal(client, session) -> None:
    custom = create_food(
        session,
        FoodCreate(
            canonical_name="Protein Coffee",
            serving_description="1 mug",
            grams_per_serving=1,
            calories=180,
            protein_g=30,
            carbs_g=6,
            fat_g=4,
        ),
    )

    response = client.post(
        "/log/submit",
        data={
            "raw_input_text": "protein coffee, wrong thing",
            "meal_label": "Breakfast",
            "logged_at": "2026-04-29T09:00:00",
            "item_count": "2",
            "candidate_json": "[[], []]",
            "parsed_phrase_0": "protein coffee",
            "quantity_0": "1",
            "unit_0": "serving",
            "quantity_text_0": "1",
            "selected_food_id_0": f"food:{custom.id}",
            "parsed_phrase_1": "wrong thing",
            "quantity_1": "1",
            "unit_1": "serving",
            "quantity_text_1": "1",
            "selected_food_id_1": "exclude",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/daily/2026-04-29"

    items = session.query(MealEntryItem).all()
    assert len(items) == 1
    assert items[0].resolved_food_name == "Protein Coffee"


def test_review_submit_with_all_items_excluded_creates_no_meal(client, session) -> None:
    response = client.post(
        "/log/submit",
        data={
            "raw_input_text": "skip this",
            "meal_label": "Breakfast",
            "logged_at": "2026-04-29T09:00:00",
            "item_count": "1",
            "candidate_json": "[[]]",
            "parsed_phrase_0": "skip this",
            "quantity_0": "1",
            "unit_0": "serving",
            "quantity_text_0": "1",
            "selected_food_id_0": "exclude",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/daily/2026-04-29"
    assert session.query(MealEntry).count() == 0
    assert session.query(MealEntryItem).count() == 0


def test_dashboard_meal_rows_link_to_food_detail(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Linked Dashboard Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=3,
        ),
    )
    entry = MealEntry(raw_input_text="linked dashboard food", meal_label="Breakfast")
    session.add(entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=entry.id,
            food_id=food.id,
            parsed_phrase="linked dashboard food",
            normalized_phrase="linked dashboard food",
            quantity=1,
            unit="serving",
            quantity_text="1",
            resolution_status="resolved",
            resolution_strategy="logged",
            resolution_confidence=1.0,
            resolved_food_name=food.canonical_name,
            resolved_source=food.source,
            calories_snapshot=100,
            protein_g_snapshot=10,
            carbs_g_snapshot=5,
            fat_g_snapshot=3,
        )
    )
    session.commit()

    response = client.get(f"/?target_date={entry.logged_at.date().isoformat()}")
    assert response.status_code == 200
    assert f'href="/foods/{food.id}"' in response.text


def test_dashboard_and_daily_render_meal_level_actions(client) -> None:
    dashboard = client.get("/")
    daily = client.get(f"/daily/{date.today().isoformat()}")
    for body in [dashboard.text, daily.text]:
        assert "Copy To..." in body
        assert "Reorder / Move" in body
        assert "Remove All" in body
        assert 'id="meal-copy-modal"' in body


def test_meal_group_copy_move_and_clear_actions_work(client, session) -> None:
    food = create_food(
        session,
        FoodCreate(
            canonical_name="Route Test Food",
            serving_description="1 serving",
            grams_per_serving=1,
            calories=100,
            protein_g=10,
            carbs_g=5,
            fat_g=4,
        ),
    )
    source_entry = MealEntry(raw_input_text="Breakfast meal", meal_label="Breakfast", logged_at=datetime.now(UTC))
    session.add(source_entry)
    session.flush()
    item = MealEntryItem(
        meal_entry_id=source_entry.id,
        food_id=food.id,
        parsed_phrase="route test food",
        normalized_phrase="route test food",
        quantity=1.0,
        unit="serving",
        quantity_text="1",
        resolution_status="resolved",
        resolution_strategy="custom_exact",
        resolution_confidence=1.0,
        resolved_food_name=food.canonical_name,
        resolved_source="custom",
        serving_description_snapshot=food.serving_description,
        grams_per_serving_snapshot=food.grams_per_serving,
        calories_snapshot=food.calories,
        protein_g_snapshot=food.protein_g,
        carbs_g_snapshot=food.carbs_g,
        fat_g_snapshot=food.fat_g,
        fiber_g_snapshot=food.fiber_g,
        net_carbs_g_snapshot=food.net_carbs_g,
    )
    session.add(item)
    session.commit()

    copy_response = client.post(
        "/meals/copy",
        data={
            "source_date": source_entry.logged_at.date().isoformat(),
            "source_meal_label": "Breakfast",
            "target_date": source_entry.logged_at.date().isoformat(),
            "target_meal_label": "Lunch",
            "redirect_to": "/",
        },
        follow_redirects=False,
    )
    assert copy_response.status_code == 303
    lunch_entries = session.query(MealEntry).filter(MealEntry.meal_label == "Lunch").all()
    assert lunch_entries
    assert any(entry.items for entry in lunch_entries)

    move_response = client.post(
        f"/meal-items/{item.id}/move",
        data={
            "target_date": source_entry.logged_at.date().isoformat(),
            "target_meal_label": "Dinner",
            "redirect_to": "/",
        },
        follow_redirects=False,
    )
    assert move_response.status_code == 303
    dinner_entries = session.query(MealEntry).filter(MealEntry.meal_label == "Dinner").all()
    assert dinner_entries
    assert any(entry.items for entry in dinner_entries)

    clear_response = client.post(
        "/meals/clear",
        data={
            "source_date": source_entry.logged_at.date().isoformat(),
            "source_meal_label": "Lunch",
            "redirect_to": "/",
        },
        follow_redirects=False,
    )
    assert clear_response.status_code == 303
    remaining_lunch = session.query(MealEntry).filter(MealEntry.meal_label == "Lunch").all()
    assert remaining_lunch == []
