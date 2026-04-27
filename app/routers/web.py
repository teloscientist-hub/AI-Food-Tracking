from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import DailyTarget, ExerciseCheckIn, ExerciseGoal, HealthGoal, HealthMeasurement
from app.schemas.foods import FoodCreate, FoodUpdate
from app.schemas.logging import LogMealRequest, LogReviewItem
from app.services.food_service import (
    create_food,
    food_to_read,
    get_food_library_cards,
    get_picker_foods,
    get_food,
    search_foods,
    update_food,
)
from app.services.logging_service import LoggingService
from app.services.summary_service import SummaryService


templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


def _progress(consumed: float, target: float | None) -> float:
    if not target or target <= 0:
        return 0
    return max(0.0, min(100.0, round((consumed / target) * 100, 1)))


def _group_entries_by_meal(entries: list) -> list[dict]:
    grouped: dict[str, dict] = {}
    for entry in entries:
        label = entry.meal_label or "General"
        if label not in grouped:
            grouped[label] = {
                "label": label,
                "entries": [],
                "totals": {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "net_carbs": 0.0},
            }
        grouped[label]["entries"].append(entry)
        for item in entry.items:
            grouped[label]["totals"]["calories"] += item.calories_snapshot
            grouped[label]["totals"]["protein"] += item.protein_g_snapshot
            grouped[label]["totals"]["carbs"] += item.carbs_g_snapshot
            grouped[label]["totals"]["fat"] += item.fat_g_snapshot
            grouped[label]["totals"]["net_carbs"] += item.net_carbs_g_snapshot or item.carbs_g_snapshot
    return list(grouped.values())


def _dashboard_meal_sections(entries: list) -> list[dict]:
    grouped_map = {group["label"]: group for group in _group_entries_by_meal(entries)}
    sections: list[dict] = []
    for label in MEAL_OPTIONS[:-1]:
        sections.append(
            grouped_map.get(
                label,
                {
                    "label": label,
                    "entries": [],
                    "totals": {
                        "calories": 0.0,
                        "protein": 0.0,
                        "carbs": 0.0,
                        "fat": 0.0,
                        "net_carbs": 0.0,
                    },
                },
            )
        )
    return sections


def _parse_selected_food_value(selection: str) -> tuple[str, int | None]:
    cleaned = selection.strip()
    if not cleaned or cleaned in {"unresolved", "none", "null"}:
        return ("unresolved", None)
    if cleaned.isdigit():
        return ("food", int(cleaned))
    if cleaned.startswith("food:"):
        tail = cleaned.split(":", 1)[1].strip()
        return ("food", int(tail)) if tail.isdigit() else ("unresolved", None)
    if cleaned.startswith("external:"):
        tail = cleaned.split(":", 1)[1].strip()
        return ("external", int(tail)) if tail.isdigit() else ("unresolved", None)
    return ("unresolved", None)


MEAL_OPTIONS = ["Breakfast", "Lunch", "Dinner", "Snack 1", "Snack 2", "Snack 3", "Supplements"]


@router.get("/")
def dashboard(
    request: Request,
    metric: str = "calories",
    meal_label: str = "Breakfast",
    logged_at: str = "",
    error: str = "",
    session: Session = Depends(get_session),
) -> object:
    today = date.today()
    summary_service = SummaryService()
    daily = summary_service.get_daily_summary(session, today)
    weekly = summary_service.get_weekly_summary(session, today, metric)
    entries = summary_service.get_daily_log(session, today)
    context = summary_service.get_dashboard_context(session, today)
    max_metric = max([day.get(metric if metric == "calories" else f"{metric}_g", 0) for day in weekly["days"]] or [1])
    progress = {
        "calories": _progress(daily["calories"]["consumed"], daily["calories"]["target"]),
        "protein": _progress(daily["protein"]["consumed"], daily["protein"]["target"]),
        "carbs": _progress(daily["carbs"]["consumed"], daily["carbs"]["target"]),
        "fat": _progress(daily["fat"]["consumed"], daily["fat"]["target"]),
        "fiber": _progress(
            daily["fiber"]["consumed"] if daily["fiber"] else 0,
            daily["fiber"]["target"] if daily["fiber"] else None,
        ),
        "net_carbs": _progress(
            daily["net_carbs"]["consumed"] if daily["net_carbs"] else 0,
            daily["net_carbs"]["target"] if daily["net_carbs"] else None,
        ),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "daily": daily,
            "weekly": weekly,
            "metric": metric,
            "max_metric": max_metric or 1,
            "progress": progress,
            "goal_rings": [
                {"label": "Net Carbs", "color": "#df5a57", "percent": progress["net_carbs"]},
                {"label": "Protein", "color": "#3a74b9", "percent": progress["protein"]},
                {"label": "Fat", "color": "#e39a36", "percent": progress["fat"]},
            ],
            "weekly_metric_key": metric if metric == "calories" else f"{metric}_g",
            "context": context,
            "meal_sections": _dashboard_meal_sections(entries),
            "today": datetime.now().isoformat(timespec="minutes"),
            "meal_label": meal_label,
            "logged_at": logged_at or datetime.now().isoformat(timespec="minutes"),
            "meal_options": MEAL_OPTIONS[:-1],
            "exercise_checkin": context["exercise_checkin"],
            "error": error,
        },
    )


@router.post("/dashboard/note")
def save_dashboard_note(
    note_body: str = Form(""),
    note_date: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    target_date = date.fromisoformat(note_date) if note_date else date.today()
    SummaryService().save_daily_note(session, target_date, note_body)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/exercise")
def save_dashboard_exercise(
    checkin_date: str = Form(""),
    did_zone2: str | None = Form(None),
    zone4_minutes: float = Form(0.0),
    did_push_workout: str | None = Form(None),
    did_pull_workout: str | None = Form(None),
    session: Session = Depends(get_session),
) -> object:
    target_date = date.fromisoformat(checkin_date) if checkin_date else date.today()
    checkin = session.scalar(select(ExerciseCheckIn).where(ExerciseCheckIn.checkin_date == target_date))
    values = {
        "did_zone2": bool(did_zone2),
        "zone4_minutes": zone4_minutes,
        "did_push_workout": bool(did_push_workout),
        "did_pull_workout": bool(did_pull_workout),
    }
    if checkin:
        checkin.did_zone2 = values["did_zone2"]
        checkin.zone4_minutes = values["zone4_minutes"]
        checkin.did_push_workout = values["did_push_workout"]
        checkin.did_pull_workout = values["did_pull_workout"]
    else:
        session.add(ExerciseCheckIn(checkin_date=target_date, **values))
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/log")
def add_log_entry(
    request: Request,
    q: str | None = None,
    source: str = "all",
    meal_label: str = "Breakfast",
    logged_at: str = "",
    saved: str | None = None,
    error: str = "",
    session: Session = Depends(get_session),
) -> object:
    picker_foods = get_picker_foods(session, q, source)
    return templates.TemplateResponse(
        request,
        "add_log.html",
        {
            "today": datetime.now().isoformat(timespec="minutes"),
            "picker_foods": picker_foods,
            "q": q or "",
            "source": source,
            "meal_label": meal_label,
            "logged_at": logged_at or datetime.now().isoformat(timespec="minutes"),
            "saved": saved or "",
            "error": error,
            "meal_options": MEAL_OPTIONS,
        },
    )


@router.get("/settings")
def settings_page(
    request: Request,
    saved: str | None = None,
    session: Session = Depends(get_session),
) -> object:
    target = session.scalar(select(DailyTarget).where(DailyTarget.target_date == date.today()))
    if not target:
        target = session.scalar(select(DailyTarget).order_by(DailyTarget.target_date.desc()).limit(1))
    protein_target = target.protein_target_g if target else 180.0
    fat_target = target.fat_target_g if target else 70.0
    net_carbs_target = target.net_carbs_target_g if target and target.net_carbs_target_g is not None else 40.0
    fiber_target = target.fiber_target_g if target and target.fiber_target_g is not None else 30.0
    total_carbs_target = target.carbs_target_g if target else (net_carbs_target + fiber_target)
    calculated_calories = round((protein_target * 4) + (fat_target * 9) + (total_carbs_target * 4), 2)
    try:
        health_goal = session.scalar(select(HealthGoal).where(HealthGoal.target_date == date.today()))
        if not health_goal:
            health_goal = session.scalar(select(HealthGoal).order_by(HealthGoal.target_date.desc()).limit(1))
    except OperationalError:
        health_goal = None
    try:
        exercise_goal = session.scalar(select(ExerciseGoal).where(ExerciseGoal.target_date == date.today()))
        if not exercise_goal:
            exercise_goal = session.scalar(select(ExerciseGoal).order_by(ExerciseGoal.target_date.desc()).limit(1))
    except OperationalError:
        exercise_goal = None
    try:
        health_measurement = session.scalar(
            select(HealthMeasurement).where(HealthMeasurement.measurement_date == date.today())
        )
        if not health_measurement:
            health_measurement = session.scalar(
                select(HealthMeasurement).order_by(HealthMeasurement.measurement_date.desc()).limit(1)
            )
    except OperationalError:
        health_measurement = None
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "saved": saved or "",
            "settings": {
                "protein_target_g": protein_target,
                "fat_target_g": fat_target,
                "net_carbs_target_g": net_carbs_target,
                "fiber_target_g": fiber_target,
                "carbs_target_g": total_carbs_target,
                "calories_target": target.calories_target if target else calculated_calories,
                "calculated_calories": calculated_calories,
            },
            "health": {
                "weight_lb": health_goal.weight_lb if health_goal and health_goal.weight_lb is not None else 190,
                "current_weight_lb": health_measurement.weight_lb if health_measurement and health_measurement.weight_lb is not None else 190,
                "weight_direction": health_goal.weight_direction if health_goal else "below",
                "body_fat_pct": health_goal.body_fat_pct if health_goal and health_goal.body_fat_pct is not None else 12,
                "current_body_fat_pct": health_measurement.body_fat_pct if health_measurement and health_measurement.body_fat_pct is not None else 12,
                "body_fat_direction": health_goal.body_fat_direction if health_goal else "below",
                "lean_body_mass_lb": health_goal.lean_body_mass_lb if health_goal and health_goal.lean_body_mass_lb is not None else 165,
                "current_lean_body_mass_lb": health_measurement.lean_body_mass_lb if health_measurement and health_measurement.lean_body_mass_lb is not None else 165,
                "lean_body_mass_direction": health_goal.lean_body_mass_direction if health_goal else "above",
                "measurement_date": health_measurement.measurement_date.isoformat() if health_measurement else date.today().isoformat(),
            },
            "exercise": {
                "zone2_cardio_minutes_per_week": exercise_goal.zone2_cardio_minutes_per_week if exercise_goal and exercise_goal.zone2_cardio_minutes_per_week is not None else 120,
                "zone4_cardio_sessions_per_week": exercise_goal.zone4_cardio_sessions_per_week if exercise_goal and exercise_goal.zone4_cardio_sessions_per_week is not None else 2,
                "push_workouts_per_week": exercise_goal.push_workouts_per_week if exercise_goal and exercise_goal.push_workouts_per_week is not None else 2,
                "pull_workouts_per_week": exercise_goal.pull_workouts_per_week if exercise_goal and exercise_goal.pull_workouts_per_week is not None else 2,
                "hangs_minutes_per_week": exercise_goal.hangs_minutes_per_week if exercise_goal and exercise_goal.hangs_minutes_per_week is not None else 15,
                "mobility_minutes_per_week": exercise_goal.mobility_minutes_per_week if exercise_goal and exercise_goal.mobility_minutes_per_week is not None else 60,
            },
        },
    )


@router.post("/settings")
def save_settings(
    protein_target_g: float = Form(...),
    fat_target_g: float = Form(...),
    net_carbs_target_g: float = Form(...),
    fiber_target_g: float = Form(0.0),
    calories_target: float = Form(...),
    weight_lb: float = Form(190.0),
    current_weight_lb: float = Form(190.0),
    weight_direction: str = Form("below"),
    body_fat_pct: float = Form(12.0),
    current_body_fat_pct: float = Form(12.0),
    body_fat_direction: str = Form("below"),
    lean_body_mass_lb: float = Form(165.0),
    current_lean_body_mass_lb: float = Form(165.0),
    lean_body_mass_direction: str = Form("above"),
    session: Session = Depends(get_session),
) -> object:
    target_date = date.today()
    target = session.scalar(select(DailyTarget).where(DailyTarget.target_date == target_date))
    health_goal = session.scalar(select(HealthGoal).where(HealthGoal.target_date == target_date))
    health_measurement = session.scalar(
        select(HealthMeasurement).where(HealthMeasurement.measurement_date == target_date)
    )
    carbs_target_g = round(net_carbs_target_g + fiber_target_g, 2)
    if target:
        target.protein_target_g = protein_target_g
        target.fat_target_g = fat_target_g
        target.net_carbs_target_g = net_carbs_target_g
        target.fiber_target_g = fiber_target_g
        target.carbs_target_g = carbs_target_g
        target.calories_target = calories_target
    else:
        session.add(
            DailyTarget(
                target_date=target_date,
                protein_target_g=protein_target_g,
                fat_target_g=fat_target_g,
                net_carbs_target_g=net_carbs_target_g,
                fiber_target_g=fiber_target_g,
                carbs_target_g=carbs_target_g,
                calories_target=calories_target,
            )
        )
    if health_goal:
        health_goal.weight_lb = weight_lb
        health_goal.weight_direction = weight_direction
        health_goal.body_fat_pct = body_fat_pct
        health_goal.body_fat_direction = body_fat_direction
        health_goal.lean_body_mass_lb = lean_body_mass_lb
        health_goal.lean_body_mass_direction = lean_body_mass_direction
    else:
        session.add(
            HealthGoal(
                target_date=target_date,
                weight_lb=weight_lb,
                weight_direction=weight_direction,
                body_fat_pct=body_fat_pct,
                body_fat_direction=body_fat_direction,
                lean_body_mass_lb=lean_body_mass_lb,
                lean_body_mass_direction=lean_body_mass_direction,
            )
        )
    if health_measurement:
        health_measurement.weight_lb = current_weight_lb
        health_measurement.body_fat_pct = current_body_fat_pct
        health_measurement.lean_body_mass_lb = current_lean_body_mass_lb
    else:
        session.add(
            HealthMeasurement(
                measurement_date=target_date,
                weight_lb=current_weight_lb,
                body_fat_pct=current_body_fat_pct,
                lean_body_mass_lb=current_lean_body_mass_lb,
            )
        )
    session.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/exercise")
def save_exercise_settings(
    zone2_cardio_minutes_per_week: float = Form(120.0),
    zone4_cardio_sessions_per_week: int = Form(2),
    push_workouts_per_week: int = Form(2),
    pull_workouts_per_week: int = Form(2),
    hangs_minutes_per_week: float = Form(15.0),
    mobility_minutes_per_week: float = Form(60.0),
    session: Session = Depends(get_session),
) -> object:
    target_date = date.today()
    exercise_goal = session.scalar(select(ExerciseGoal).where(ExerciseGoal.target_date == target_date))
    if exercise_goal:
        exercise_goal.zone2_cardio_minutes_per_week = zone2_cardio_minutes_per_week
        exercise_goal.zone4_cardio_sessions_per_week = zone4_cardio_sessions_per_week
        exercise_goal.push_workouts_per_week = push_workouts_per_week
        exercise_goal.pull_workouts_per_week = pull_workouts_per_week
        exercise_goal.hangs_minutes_per_week = hangs_minutes_per_week
        exercise_goal.mobility_minutes_per_week = mobility_minutes_per_week
    else:
        session.add(
            ExerciseGoal(
                target_date=target_date,
                zone2_cardio_minutes_per_week=zone2_cardio_minutes_per_week,
                zone4_cardio_sessions_per_week=zone4_cardio_sessions_per_week,
                push_workouts_per_week=push_workouts_per_week,
                pull_workouts_per_week=pull_workouts_per_week,
                hangs_minutes_per_week=hangs_minutes_per_week,
                mobility_minutes_per_week=mobility_minutes_per_week,
            )
        )
    session.commit()
    return RedirectResponse(url="/settings?saved=exercise", status_code=303)


@router.get("/log/picker")
def picker_log_entry(
    request: Request,
    q: str | None = None,
    source: str = "all",
    meal_label: str = "Breakfast",
    logged_at: str = "",
    saved: str | None = None,
    session: Session = Depends(get_session),
) -> object:
    picker_foods = get_picker_foods(session, q, source)
    return templates.TemplateResponse(
        request,
        "log_picker.html",
        {
            "picker_foods": picker_foods,
            "q": q or "",
            "source": source,
            "meal_label": meal_label,
            "logged_at": logged_at or datetime.now().isoformat(timespec="minutes"),
            "saved": saved or "",
            "meal_options": MEAL_OPTIONS,
        },
    )


@router.post("/log/picker/add")
def add_picker_food(
    food_id: int = Form(...),
    quantity: float = Form(1.0),
    unit: str = Form(""),
    meal_label: str = Form("Breakfast"),
    logged_at: str = Form(""),
    q: str = Form(""),
    source: str = Form("all"),
    redirect_to: str = Form("/log/picker"),
    session: Session = Depends(get_session),
) -> object:
    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    service = LoggingService()
    service.save_meal(
        session,
        LogMealRequest(
            raw_input_text=f"{quantity:g} {food.canonical_name}",
            meal_label=meal_label,
            logged_at=datetime.fromisoformat(logged_at) if logged_at else None,
            items=[
                LogReviewItem(
                    parsed_phrase=food.canonical_name,
                    quantity=quantity,
                    unit=unit or None,
                    quantity_text=str(quantity),
                    selected_food_id=food.id,
                    always_map=False,
                )
            ],
        ),
    )
    params = urlencode(
        {
            "q": q,
            "source": source,
            "meal_label": meal_label,
            "logged_at": logged_at,
            "saved": food.canonical_name,
        }
    )
    target = redirect_to if redirect_to in {"/log", "/log/picker"} else "/log/picker"
    return RedirectResponse(url=f"{target}?{params}", status_code=303)


@router.post("/log/review")
def review_log_entry(
    request: Request,
    raw_input_text: str = Form(""),
    meal_label: str = Form("General"),
    logged_at: str = Form(""),
    redirect_to: str = Form("/log"),
    session: Session = Depends(get_session),
) -> object:
    if not raw_input_text.strip():
        target = redirect_to if redirect_to in {"/", "/log"} else "/log"
        params = urlencode(
            {
                "error": "Please enter a food description before parsing.",
                "meal_label": meal_label,
                "logged_at": logged_at,
            }
        )
        return RedirectResponse(url=f"{target}?{params}", status_code=303)
    service = LoggingService()
    review = service.build_review(session, raw_input_text)
    return templates.TemplateResponse(
        request,
        "review_entry.html",
        {
            "raw_input_text": raw_input_text,
            "meal_label": meal_label,
            "logged_at": logged_at,
            "review": review,
            "candidate_json": json.dumps(
                [
                    [asdict(candidate) for candidate in item.candidates]
                    for item in review
                ]
            ),
        },
    )


@router.post("/log/submit")
async def submit_log_entry(
    request: Request,
    raw_input_text: str = Form(...),
    meal_label: str = Form("General"),
    logged_at: str = Form(""),
    item_count: int = Form(...),
    candidate_json: str = Form(...),
    session: Session = Depends(get_session),
) -> object:
    form = await request.form()
    candidate_groups = json.loads(candidate_json)
    service = LoggingService()
    items: list[LogReviewItem] = []
    for index in range(item_count):
        selection = str(form.get(f"selected_food_id_{index}", "")).strip()
        selection_kind, selection_value = _parse_selected_food_value(selection)
        selected_food_id: int | None = None
        if selection_kind == "food":
            selected_food_id = selection_value
        elif selection_kind == "external":
            candidate_index = selection_value if selection_value is not None else -1
            imported = service.persist_external_candidate(session, candidate_index, candidate_groups[index])
            selected_food_id = imported.id

        items.append(
            LogReviewItem(
                parsed_phrase=str(form.get(f"parsed_phrase_{index}", "")),
                quantity=float(form.get(f"quantity_{index}", 1)),
                unit=str(form.get(f"unit_{index}", "")) or None,
                quantity_text=str(form.get(f"quantity_text_{index}", "")) or None,
                selected_food_id=selected_food_id,
                always_map=bool(form.get(f"always_map_{index}")),
            )
        )

    service.save_meal(
        session,
        LogMealRequest(
            raw_input_text=raw_input_text,
            meal_label=meal_label,
            logged_at=datetime.fromisoformat(logged_at) if logged_at else None,
            items=items,
        ),
    )
    return RedirectResponse(url="/", status_code=303)


@router.get("/foods")
def foods_library(
    request: Request,
    q: str | None = None,
    source: str = "all",
    session: Session = Depends(get_session),
) -> object:
    food_cards = get_food_library_cards(session, q, source)
    return templates.TemplateResponse(
        request,
        "foods_library.html",
        {"food_cards": food_cards, "q": q or "", "source": source},
    )


@router.post("/foods/{food_id}/duplicate")
def duplicate_food_web(food_id: int, session: Session = Depends(get_session)) -> object:
    from app.services.food_service import duplicate_food_to_custom

    duplicate_food_to_custom(session, food_id)
    return RedirectResponse(url="/foods?source=custom", status_code=303)


@router.get("/foods/{food_id}")
def food_detail(
    request: Request, food_id: int, session: Session = Depends(get_session)
) -> object:
    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    return templates.TemplateResponse(
        request,
        "food_detail.html",
        {"food": food_to_read(session, food), "meal_options": MEAL_OPTIONS},
    )


@router.get("/foods/custom/new")
def new_custom_food(request: Request, prefill_phrase: str | None = None) -> object:
    return templates.TemplateResponse(
        request,
        "custom_food_editor.html",
        {"food": None, "prefill_phrase": prefill_phrase or "", "mode": "create"},
    )


@router.get("/foods/{food_id}/edit")
def edit_custom_food(
    request: Request, food_id: int, session: Session = Depends(get_session)
) -> object:
    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    return templates.TemplateResponse(
        request,
        "custom_food_editor.html",
        {"food": food_to_read(session, food), "prefill_phrase": "", "mode": "edit"},
    )


@router.post("/foods/custom/save")
def save_custom_food(
    canonical_name: str = Form(...),
    brand: str | None = Form(None),
    serving_description: str = Form(...),
    grams_per_serving: float = Form(...),
    calories: float = Form(...),
    protein_g: float = Form(...),
    carbs_g: float = Form(...),
    fat_g: float = Form(...),
    fiber_g: float | None = Form(None),
    net_carbs_g: float | None = Form(None),
    aliases: str = Form(""),
    authoritative_locked: bool = Form(False),
    notes: str | None = Form(None),
    session: Session = Depends(get_session),
) -> object:
    payload = FoodCreate(
        canonical_name=canonical_name,
        brand=brand or None,
        serving_description=serving_description,
        grams_per_serving=grams_per_serving,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        fiber_g=fiber_g,
        net_carbs_g=net_carbs_g,
        aliases=[item.strip() for item in aliases.split(",") if item.strip()],
        authoritative_locked=authoritative_locked,
        notes=notes,
    )
    create_food(session, payload)
    return RedirectResponse(url="/foods", status_code=303)


@router.post("/foods/{food_id}/save")
def save_existing_custom_food(
    food_id: int,
    canonical_name: str = Form(...),
    brand: str | None = Form(None),
    serving_description: str = Form(...),
    grams_per_serving: float = Form(...),
    calories: float = Form(...),
    protein_g: float = Form(...),
    carbs_g: float = Form(...),
    fat_g: float = Form(...),
    fiber_g: float | None = Form(None),
    net_carbs_g: float | None = Form(None),
    aliases: str = Form(""),
    authoritative_locked: bool = Form(False),
    notes: str | None = Form(None),
    session: Session = Depends(get_session),
) -> object:
    payload = FoodUpdate(
        canonical_name=canonical_name,
        brand=brand or None,
        serving_description=serving_description,
        grams_per_serving=grams_per_serving,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        fiber_g=fiber_g,
        net_carbs_g=net_carbs_g,
        aliases=[item.strip() for item in aliases.split(",") if item.strip()],
        authoritative_locked=authoritative_locked,
        notes=notes,
    )
    update_food(session, food_id, payload)
    return RedirectResponse(url="/foods", status_code=303)


@router.get("/daily/{target_date}")
def daily_log_detail(
    request: Request, target_date: date, session: Session = Depends(get_session)
) -> object:
    summary_service = SummaryService()
    entries = summary_service.get_daily_log(session, target_date)
    daily = summary_service.get_daily_summary(session, target_date)
    return templates.TemplateResponse(
        request,
        "daily_log.html",
        {
            "entries": entries,
            "daily": daily,
            "target_date": target_date.isoformat(),
            "meal_groups": _group_entries_by_meal(entries),
        },
    )


@router.get("/weekly")
def weekly_trends(
    request: Request,
    metric: str = "calories",
    session: Session = Depends(get_session),
) -> object:
    weekly = SummaryService().get_weekly_summary(session, date.today(), metric)
    max_metric = max([day.get(metric if metric == "calories" else f"{metric}_g", 0) for day in weekly["days"]] or [1])
    return templates.TemplateResponse(
        request,
        "weekly_trends.html",
        {"weekly": weekly, "metric": metric, "max_metric": max_metric or 1},
    )
