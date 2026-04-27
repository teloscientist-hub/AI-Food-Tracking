from datetime import UTC, date, datetime, timedelta

from app.models import DailyNote, ExerciseCheckIn, MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate
from app.schemas.logging import LogMealRequest, LogReviewItem
from app.services.food_service import create_food
from app.services.logging_service import LoggingService
from app.services.summary_service import SummaryService


def test_daily_summary_calculates_totals_status_and_streak(session) -> None:
    egg = create_food(
        session,
        FoodCreate(
            canonical_name="Egg",
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
            fiber_g=0.0,
            net_carbs_g=0.4,
        ),
    )

    service = LoggingService()
    today = date.today()
    yesterday = today - timedelta(days=1)
    service.save_meal(
        session,
        LogMealRequest(
            raw_input_text="2 eggs",
            meal_label="Breakfast",
            logged_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
            items=[LogReviewItem(parsed_phrase="eggs", quantity=2, selected_food_id=egg.id)],
        ),
    )
    service.save_meal(
        session,
        LogMealRequest(
            raw_input_text="1 egg",
            meal_label="Breakfast",
            logged_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC),
            items=[LogReviewItem(parsed_phrase="egg", quantity=1, selected_food_id=egg.id)],
        ),
    )

    summary = SummaryService().get_daily_summary(session, today)

    assert summary["calories"]["consumed"] == 144.0
    assert summary["protein"]["consumed"] == 12.0
    assert summary["fat"]["consumed"] == 10.0
    assert summary["net_carbs"]["consumed"] == 0.8
    assert summary["streak_days"] == 2
    assert summary["status_text"] == "Under target"


def test_weekly_summary_reports_averages_and_top_foods(session) -> None:
    egg = create_food(
        session,
        FoodCreate(
            canonical_name="Egg",
            serving_description="1 egg",
            grams_per_serving=50,
            calories=72,
            protein_g=6,
            carbs_g=0.4,
            fat_g=5,
            net_carbs_g=0.4,
        ),
    )
    yogurt = create_food(
        session,
        FoodCreate(
            canonical_name="Greek Yogurt",
            serving_description="1 cup",
            grams_per_serving=150,
            calories=120,
            protein_g=15,
            carbs_g=8,
            fat_g=0,
            net_carbs_g=8,
        ),
    )

    logger = LoggingService()
    end_date = date.today()
    for offset in range(3):
        target_day = end_date - timedelta(days=offset)
        logger.save_meal(
            session,
            LogMealRequest(
                raw_input_text="meal",
                meal_label="Breakfast",
                logged_at=datetime.combine(target_day, datetime.min.time(), tzinfo=UTC),
                items=[
                    LogReviewItem(parsed_phrase="egg", quantity=2, selected_food_id=egg.id),
                    LogReviewItem(parsed_phrase="yogurt", quantity=1, selected_food_id=yogurt.id),
                ],
            ),
        )

    weekly = SummaryService().get_weekly_summary(session, end_date)

    assert len(weekly["days"]) == 7
    assert weekly["averages"]["calories"] > 0
    assert weekly["averages"]["protein_g"] > 0
    assert weekly["top_foods"][0]["name"] == "Greek Yogurt"
    assert weekly["top_foods"][0]["value"] == 45.0


def test_dashboard_context_includes_counts_note_and_exercise(session) -> None:
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
    meal_entry = MealEntry(
        raw_input_text="mystery food",
        meal_label="Breakfast",
        logged_at=datetime.now(UTC),
    )
    session.add(meal_entry)
    session.flush()
    session.add(
        MealEntryItem(
            meal_entry_id=meal_entry.id,
            food_id=None,
            parsed_phrase="mystery food",
            normalized_phrase="mystery food",
            quantity=1.0,
            unit=None,
            resolution_status="unresolved",
            resolution_strategy="deferred",
            resolution_confidence=0.0,
            resolved_food_name=None,
            resolved_source=None,
            serving_description_snapshot=None,
            grams_per_serving_snapshot=None,
            calories_snapshot=0.0,
            protein_g_snapshot=0.0,
            carbs_g_snapshot=0.0,
            fat_g_snapshot=0.0,
            fiber_g_snapshot=None,
            net_carbs_g_snapshot=None,
        )
    )
    session.add(DailyNote(note_date=date.today(), body="Watch sodium"))
    session.add(
        ExerciseCheckIn(
            checkin_date=date.today(),
            did_zone2=True,
            zone4_minutes=18,
            did_push_workout=True,
            did_pull_workout=False,
        )
    )
    session.commit()

    context = SummaryService().get_dashboard_context(session, date.today())

    assert context["custom_food_count"] >= 1
    assert context["unresolved_count"] == 1
    assert context["daily_note"] == "Watch sodium"
    assert context["exercise_checkin"]["did_zone2"] is True
    assert context["exercise_checkin"]["zone4_minutes"] == 18
    assert context["exercise_checkin"]["did_push_workout"] is True
    assert context["exercise_checkin"]["did_pull_workout"] is False
