from datetime import UTC, datetime

from app.schemas.foods import FoodCreate
from app.services.food_service import create_food


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
        assert f'href="/log?meal_label={meal.replace(" ", "%20")}"' in body or f'href="/log?meal_label={meal}"' in body

    foods = client.get("/foods")
    foods_body = foods.text
    assert 'href="/foods/custom/new"' in foods_body


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

    page = client.get("/foods")
    assert page.status_code == 200
    assert f'href="/foods/{custom.id}/edit"' in page.text
    assert f'action="/foods/{external.id}/duplicate"' in page.text

    duplicate_response = client.post(f"/foods/{external.id}/duplicate", follow_redirects=False)
    assert duplicate_response.status_code == 303


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
