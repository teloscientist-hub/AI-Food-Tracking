import io
import json
from datetime import UTC, date, datetime, timedelta

from app.models import MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate
from app.services.food_service import create_food
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


def test_dashboard_week_panel_renders_goal_based_axis_labels(client) -> None:
    response = client.get("/?metric=calories")
    assert response.status_code == 200
    assert 'class="week-axis"' in response.text
    assert ">500<" in response.text
    assert ">1000<" in response.text


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

    response = client.get("/")
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
