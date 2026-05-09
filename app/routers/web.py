from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import DailyTarget, ExerciseCheckIn, ExerciseGoal, Food, HealthGoal, HealthMeasurement, MealEntry, MealEntryItem
from app.schemas.foods import FoodCreate, FoodUpdate
from app.schemas.logging import LogMealRequest, LogReviewItem
from app.services.food_service import (
    create_food,
    food_to_read,
    get_food_library_cards,
    get_picker_foods,
    get_food,
    remove_custom_food_from_library,
    search_foods,
    update_food,
)
from app.services.food_icons import ICON_LIBRARY
from app.services.logging_service import LoggingService, multiply_value, serving_multiplier
from app.services.off_client import OpenFoodFactsClient
from app.services.summary_service import SummaryService
from app.services.usda_client import ExternalFoodCandidate, USDAClient


templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


def _progress(consumed: float, target: float | None) -> float:
    if not target or target <= 0:
        return 0
    return max(0.0, min(100.0, round((consumed / target) * 100, 1)))


def _nice_axis_step(raw_step: float) -> float:
    if raw_step <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw_step))
    fraction = raw_step / (10 ** exponent)
    if fraction <= 1.5:
        nice_fraction = 1
    elif fraction <= 3:
        nice_fraction = 2
    elif fraction <= 7:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * (10 ** exponent)


def _week_axis_for_metric(metric: str, daily: dict, weekly: dict, weekly_metric_key: str) -> dict[str, object]:
    metric_map = {
        "calories": daily["calories"]["target"],
        "protein": daily["protein"]["target"],
        "carbs": daily["carbs"]["target"],
        "fat": daily["fat"]["target"],
        "fiber": daily["fiber"]["target"] if daily["fiber"] else None,
        "net_carbs": daily["net_carbs"]["target"] if daily["net_carbs"] else None,
    }
    target = metric_map.get(metric)
    values = [float(day.get(weekly_metric_key, 0) or 0) for day in weekly["days"]]
    max_value = max(values or [0.0])

    if target and target > 0:
        step = _nice_axis_step(target / 4)
        desired_max = max(target * 2, max_value)
        axis_max = math.ceil(desired_max / step) * step
    else:
        baseline = max(max_value, 10.0)
        step = _nice_axis_step(baseline / 4)
        axis_max = max(step * 4, math.ceil(max_value / step) * step if max_value > 0 else step * 4)

    label_count = int(round(axis_max / step))
    labels = [round(step * index, 2) for index in range(label_count, 0, -1)]
    return {
        "max": float(axis_max),
        "step": float(step),
        "labels": labels,
    }


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
    if cleaned == "exclude":
        return ("exclude", None)
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


def _native_serving_unit_label(serving_description: str | None) -> str | None:
    if not serving_description:
        return None
    parts = serving_description.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0].lower()
    if parts[0].replace(".", "", 1).isdigit():
        return parts[1].lower()
    return serving_description.strip().lower()


def _detail_unit_options(serving_description: str | None) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(value: str | None, label: str | None = None) -> None:
        if not value:
            return
        cleaned = value.strip().lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        options.append({"value": cleaned, "label": label or cleaned})

    add(_native_serving_unit_label(serving_description))
    add("g", "grams")
    add("oz", "oz")
    return options


def _item_unit_options(food: Food | None, current_unit: str | None) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(value: str | None, label: str | None = None) -> None:
        if not value:
            return
        cleaned = value.strip().lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        options.append({"value": cleaned, "label": label or cleaned})

    add(current_unit)
    add(_native_serving_unit_label(food.serving_description) if food else None)
    add("g", "grams")
    add("oz", "oz")
    return options


def _redirect_path_for_date(target_date: date) -> str:
    if target_date == date.today():
        return "/"
    return f"/daily/{target_date.isoformat()}"


def _external_candidate_payload(candidate: ExternalFoodCandidate) -> dict:
    payload = asdict(candidate)
    payload["raw_payload"] = payload.pop("raw_source_payload", None)
    return payload


MEAL_OPTIONS = ["Breakfast", "Lunch", "Dinner", "Snack 1", "Snack 2", "Snack 3", "Supplements"]


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(target_date, time.min), datetime.combine(target_date, time.max)


def _meal_entries_for_date(session: Session, target_date: date, meal_label: str) -> list[MealEntry]:
    start_dt, end_dt = _day_bounds(target_date)
    return list(
        session.scalars(
            select(MealEntry)
            .where(
                MealEntry.meal_label == meal_label,
                MealEntry.logged_at >= start_dt,
                MealEntry.logged_at <= end_dt,
            )
            .order_by(MealEntry.logged_at.asc(), MealEntry.id.asc())
        )
    )


def _clone_meal_item(source_item: MealEntryItem, meal_entry_id: int) -> MealEntryItem:
    return MealEntryItem(
        meal_entry_id=meal_entry_id,
        food_id=source_item.food_id,
        parsed_phrase=source_item.parsed_phrase,
        normalized_phrase=source_item.normalized_phrase,
        quantity=source_item.quantity,
        unit=source_item.unit,
        quantity_text=source_item.quantity_text,
        resolution_status=source_item.resolution_status,
        resolution_strategy=source_item.resolution_strategy,
        resolution_confidence=source_item.resolution_confidence,
        resolved_food_name=source_item.resolved_food_name,
        resolved_source=source_item.resolved_source,
        serving_description_snapshot=source_item.serving_description_snapshot,
        grams_per_serving_snapshot=source_item.grams_per_serving_snapshot,
        calories_snapshot=source_item.calories_snapshot,
        protein_g_snapshot=source_item.protein_g_snapshot,
        carbs_g_snapshot=source_item.carbs_g_snapshot,
        fat_g_snapshot=source_item.fat_g_snapshot,
        fiber_g_snapshot=source_item.fiber_g_snapshot,
        net_carbs_g_snapshot=source_item.net_carbs_g_snapshot,
    )


def _get_or_create_target_meal_entry(session: Session, target_date: date, meal_label: str, logged_time: time | None = None) -> MealEntry:
    existing = _meal_entries_for_date(session, target_date, meal_label)
    if existing:
        return existing[0]
    meal_entry = MealEntry(
        raw_input_text=f"Meal action: {meal_label}",
        meal_label=meal_label,
        logged_at=datetime.combine(target_date, logged_time or time(hour=12)),
    )
    session.add(meal_entry)
    session.flush()
    return meal_entry


@router.get("/")
def dashboard(
    request: Request,
    metric: str = "calories",
    target_date: str = "",
    meal_label: str = "Breakfast",
    logged_at: str = "",
    error: str = "",
    session: Session = Depends(get_session),
) -> object:
    selected_date = date.fromisoformat(target_date) if target_date else date.today()
    summary_service = SummaryService()
    daily = summary_service.get_daily_summary(session, selected_date)
    weekly = summary_service.get_weekly_summary(session, selected_date, metric)
    entries = summary_service.get_daily_log(session, selected_date)
    context = summary_service.get_dashboard_context(session, selected_date)
    max_metric = max([day.get(metric if metric == "calories" else f"{metric}_g", 0) for day in weekly["days"]] or [1])
    prev_date = (selected_date.fromordinal(selected_date.toordinal() - 1)).isoformat()
    next_date = (selected_date.fromordinal(selected_date.toordinal() + 1)).isoformat()
    weekly_metric_key = metric if metric == "calories" else f"{metric}_g"
    week_axis = _week_axis_for_metric(metric, daily, weekly, weekly_metric_key)
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
            "selected_date": selected_date.isoformat(),
            "prev_date": prev_date,
            "next_date": next_date,
            "weekly_metric_key": weekly_metric_key,
            "week_axis": week_axis,
            "context": context,
            "meal_sections": _dashboard_meal_sections(entries),
            "today": datetime.now().isoformat(timespec="minutes"),
            "meal_label": meal_label,
            "logged_at": logged_at or datetime.now().isoformat(timespec="minutes"),
            "meal_options": MEAL_OPTIONS[:-1],
            "dashboard_return": f"/?target_date={selected_date.isoformat()}&metric={metric}",
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
    zone2_minutes: float = Form(0.0),
    zone4_minutes: float = Form(0.0),
    did_push_workout: str | None = Form(None),
    did_pull_workout: str | None = Form(None),
    session: Session = Depends(get_session),
) -> object:
    target_date = date.fromisoformat(checkin_date) if checkin_date else date.today()
    checkin = session.scalar(select(ExerciseCheckIn).where(ExerciseCheckIn.checkin_date == target_date))
    values = {
        "did_zone2": zone2_minutes > 0,
        "zone2_minutes": zone2_minutes,
        "zone4_minutes": zone4_minutes,
        "did_push_workout": bool(did_push_workout),
        "did_pull_workout": bool(did_pull_workout),
    }
    if checkin:
        checkin.did_zone2 = values["did_zone2"]
        checkin.zone2_minutes = values["zone2_minutes"]
        checkin.zone4_minutes = values["zone4_minutes"]
        checkin.did_push_workout = values["did_push_workout"]
        checkin.did_pull_workout = values["did_pull_workout"]
    else:
        session.add(ExerciseCheckIn(checkin_date=target_date, **values))
    session.commit()
    return RedirectResponse(url="/", status_code=303)


def _resolve_selected_date(target_date: str, logged_at: str) -> date:
    if target_date:
        return date.fromisoformat(target_date)
    if logged_at:
        try:
            return datetime.fromisoformat(logged_at).date()
        except ValueError:
            pass
    return date.today()


def _logged_at_for_date(logged_at: str, selected_date: date) -> str:
    if logged_at:
        try:
            parsed = datetime.fromisoformat(logged_at)
            return datetime.combine(selected_date, parsed.time()).isoformat(timespec="minutes")
        except ValueError:
            pass
    return datetime.combine(selected_date, datetime.now().time()).isoformat(timespec="minutes")


@router.get("/log")
def add_log_entry(
    request: Request,
    q: str | None = None,
    source: str = "all",
    meal_label: str = "Breakfast",
    logged_at: str = "",
    target_date: str = "",
    saved: str | None = None,
    error: str = "",
    session: Session = Depends(get_session),
) -> object:
    selected_date = _resolve_selected_date(target_date, logged_at)
    effective_logged_at = _logged_at_for_date(logged_at, selected_date)
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
            "logged_at": effective_logged_at,
            "saved": saved or "",
            "error": error,
            "meal_options": MEAL_OPTIONS,
            "selected_date": selected_date.isoformat(),
            "prev_date": (selected_date - timedelta(days=1)).isoformat(),
            "next_date": (selected_date + timedelta(days=1)).isoformat(),
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
    target_date: str = "",
    saved: str | None = None,
    session: Session = Depends(get_session),
) -> object:
    selected_date = _resolve_selected_date(target_date, logged_at)
    effective_logged_at = _logged_at_for_date(logged_at, selected_date)
    picker_foods = get_picker_foods(session, q, source)
    return templates.TemplateResponse(
        request,
        "log_picker.html",
        {
            "picker_foods": picker_foods,
            "q": q or "",
            "source": source,
            "meal_label": meal_label,
            "logged_at": effective_logged_at,
            "saved": saved or "",
            "meal_options": MEAL_OPTIONS,
            "selected_date": selected_date.isoformat(),
            "prev_date": (selected_date - timedelta(days=1)).isoformat(),
            "next_date": (selected_date + timedelta(days=1)).isoformat(),
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


@router.post("/log/save-custom")
async def save_custom_from_review(
    request: Request,
    raw_input_text: str = Form(...),
    meal_label: str = Form("General"),
    logged_at: str = Form(""),
    item_count: int = Form(...),
    candidate_json: str = Form(...),
    session: Session = Depends(get_session),
) -> object:
    form = await request.form()
    item_index = int(str(form.get("save_custom_index", "-1")))
    if item_index < 0 or item_index >= item_count:
        raise HTTPException(status_code=400, detail="Invalid review item")

    selection = str(form.get(f"selected_food_id_{item_index}", "")).strip()
    selection_kind, selection_value = _parse_selected_food_value(selection)
    parsed_phrase = str(form.get(f"parsed_phrase_{item_index}", "")).strip()

    if selection_kind == "unresolved":
        target = f"/foods/custom/new?prefill_phrase={parsed_phrase}" if parsed_phrase else "/foods/custom/new"
        return RedirectResponse(url=target, status_code=303)

    if selection_kind == "food":
        food = get_food(session, int(selection_value))
        if not food:
            raise HTTPException(status_code=404, detail="Food not found")
        if food.source == "custom":
            return RedirectResponse(url=f"/foods/{food.id}/edit", status_code=303)
        from app.services.food_service import duplicate_food_to_custom

        duplicate = duplicate_food_to_custom(session, food.id)
        return RedirectResponse(url=f"/foods/{duplicate.id}/edit", status_code=303)

    if selection_kind == "external":
        candidate_groups = json.loads(candidate_json)
        service = LoggingService()
        custom_food = service.save_external_candidate_as_custom(
            session,
            int(selection_value),
            candidate_groups[item_index],
            alias_phrase=parsed_phrase or None,
        )
        return RedirectResponse(url=f"/foods/{custom_food.id}/edit", status_code=303)

    raise HTTPException(status_code=400, detail="Unsupported selection for custom save")


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
        if selection_kind == "exclude":
            continue
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

    target_day = datetime.fromisoformat(logged_at).date() if logged_at else date.today()
    redirect_url = _redirect_path_for_date(target_day)
    if not items:
        return RedirectResponse(url=redirect_url, status_code=303)

    service.save_meal(
        session,
        LogMealRequest(
            raw_input_text=raw_input_text,
            meal_label=meal_label,
            logged_at=datetime.fromisoformat(logged_at) if logged_at else None,
            items=items,
        ),
    )
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/foods")
def foods_library(
    request: Request,
    q: str | None = None,
    source: str = "custom",
    sort: str = "previously_logged",
    session: Session = Depends(get_session),
) -> object:
    query = (q or "").strip()
    if source not in {"custom", "usda", "openfoodfacts"}:
        source = "custom"
    food_cards: list[dict] = []
    external_results: list[dict] = []
    external_error = ""
    external_mode = source in {"usda", "openfoodfacts"}
    external_search = external_mode and bool(query)

    if external_search:
        try:
            if source == "usda":
                candidates = USDAClient().search(query, limit=12)
            else:
                candidates = OpenFoodFactsClient().search(query, limit=12)
            external_results = [
                {
                    "candidate_json": json.dumps(_external_candidate_payload(candidate)),
                    "canonical_name": candidate.canonical_name,
                    "brand": candidate.brand,
                    "source": candidate.source,
                    "serving_description": candidate.serving_description,
                    "image_url": candidate.raw_source_payload.get("image_front_url")
                    or candidate.raw_source_payload.get("image_url")
                    or candidate.raw_source_payload.get("image_small_url"),
                    "net_carbs_g": candidate.net_carbs_g if candidate.net_carbs_g is not None else candidate.carbs_g,
                    "protein_g": candidate.protein_g,
                    "fat_g": candidate.fat_g,
                    "calories": candidate.calories,
                    "score": candidate.score,
                }
                for candidate in candidates
            ]
        except Exception as exc:
            external_error = str(exc) or f"Unable to search {source} right now."
    elif source == "custom":
        food_cards = get_food_library_cards(session, query or None, "custom", sort)

    return templates.TemplateResponse(
        request,
        "foods_library.html",
        {
            "food_cards": food_cards,
            "external_results": external_results,
            "external_mode": external_mode,
            "external_search": external_search,
            "external_error": external_error,
            "q": query,
            "source": source,
            "sort": sort,
        },
    )


@router.post("/foods/external/save")
async def save_external_food_from_library(
    request: Request,
    candidate_json: str = Form(...),
    action: str = Form(...),
    source: str = Form("custom"),
    q: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    try:
        candidate = json.loads(candidate_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid candidate payload") from exc

    custom_food = LoggingService().save_external_candidate_as_custom(session, 0, [candidate])

    if action == "save":
        redirect_q = urlencode({"source": "custom", "q": custom_food.canonical_name})
        return RedirectResponse(url=f"/foods?{redirect_q}", status_code=303)
    if action == "save_add":
        return RedirectResponse(url=f"/foods/{custom_food.id}", status_code=303)
    if action == "save_edit":
        return RedirectResponse(url=f"/foods/{custom_food.id}/edit", status_code=303)

    raise HTTPException(status_code=400, detail="Unknown external save action")


@router.post("/foods/{food_id}/duplicate")
def duplicate_food_web(food_id: int, session: Session = Depends(get_session)) -> object:
    from app.services.food_service import duplicate_food_to_custom

    duplicate = duplicate_food_to_custom(session, food_id)
    return RedirectResponse(url=f"/foods/{duplicate.id}", status_code=303)


@router.post("/foods/{food_id}/edit-copy")
def edit_food_copy_web(food_id: int, session: Session = Depends(get_session)) -> object:
    from app.services.food_service import duplicate_food_to_custom

    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    if food.source == "custom":
        return RedirectResponse(url=f"/foods/{food.id}/edit", status_code=303)
    duplicate = duplicate_food_to_custom(session, food_id)
    return RedirectResponse(url=f"/foods/{duplicate.id}/edit", status_code=303)


@router.post("/foods/{food_id}/remove")
def remove_food_from_custom_library(food_id: int, session: Session = Depends(get_session)) -> object:
    food = get_food(session, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    if food.source != "custom":
        raise HTTPException(status_code=400, detail="Only custom foods can be removed from the custom library")
    remove_custom_food_from_library(session, food_id)
    return RedirectResponse(url="/foods?source=custom", status_code=303)


@router.get("/foods/{food_id}/image")
def food_image(food_id: int, session: Session = Depends(get_session)) -> object:
    food = get_food(session, food_id)
    if not food or not food.image_data or not food.image_content_type:
        raise HTTPException(status_code=404, detail="Food image not found")
    return Response(content=food.image_data, media_type=food.image_content_type)


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
        {
            "food": food_to_read(session, food),
            "meal_options": MEAL_OPTIONS,
            "unit_options": _detail_unit_options(food.serving_description),
        },
    )


@router.get("/foods/custom/new")
def new_custom_food(request: Request, prefill_phrase: str | None = None) -> object:
    return templates.TemplateResponse(
        request,
        "custom_food_editor.html",
        {"food": None, "prefill_phrase": prefill_phrase or "", "mode": "create", "icon_library": ICON_LIBRARY},
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
        {"food": food_to_read(session, food), "prefill_phrase": "", "mode": "edit", "icon_library": ICON_LIBRARY},
    )


@router.post("/foods/custom/save")
def save_custom_food(
    canonical_name: str = Form(...),
    brand: str | None = Form(None),
    image_url: str | None = Form(None),
    icon_key: str | None = Form(None),
    image_upload: UploadFile | None = File(None),
    serving_description: str = Form(...),
    grams_per_serving: float | None = Form(None),
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
    upload_bytes = image_upload.file.read() if image_upload and image_upload.filename else None
    payload = FoodCreate(
        canonical_name=canonical_name,
        brand=brand or None,
        image_url=image_url or None,
        image_data=upload_bytes or None,
        image_content_type=image_upload.content_type if upload_bytes and image_upload else None,
        icon_key=icon_key or None,
        serving_description=serving_description,
        grams_per_serving=grams_per_serving or 1.0,
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
    image_url: str | None = Form(None),
    icon_key: str | None = Form(None),
    image_upload: UploadFile | None = File(None),
    serving_description: str = Form(...),
    grams_per_serving: float | None = Form(None),
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
    upload_bytes = image_upload.file.read() if image_upload and image_upload.filename else None
    payload = FoodUpdate(
        canonical_name=canonical_name,
        brand=brand or None,
        image_url=image_url or None,
        image_data=upload_bytes or None,
        image_content_type=image_upload.content_type if upload_bytes and image_upload else None,
        icon_key=icon_key or None,
        serving_description=serving_description,
        grams_per_serving=grams_per_serving or 1.0,
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
            "meal_groups": _dashboard_meal_sections(entries),
            "meal_options": MEAL_OPTIONS[:-1],
            "daily_return": f"/daily/{target_date.isoformat()}",
        },
    )


@router.get("/meal-items/{item_id}/edit")
def edit_meal_item_page(
    request: Request,
    item_id: int,
    redirect_to: str = "",
    session: Session = Depends(get_session),
) -> object:
    item = session.get(MealEntryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    meal_entry = session.get(MealEntry, item.meal_entry_id)
    if not meal_entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")
    return templates.TemplateResponse(
        request,
        "meal_item_edit.html",
        {
            "item": item,
            "meal_entry": meal_entry,
            "meal_options": MEAL_OPTIONS[:-1],
            "unit_options": _item_unit_options(item.food, item.unit),
            "redirect_to": redirect_to or _redirect_path_for_date(meal_entry.logged_at.date()),
        },
    )


@router.post("/meal-items/{item_id}/save")
def save_meal_item_edit(
    item_id: int,
    quantity: float = Form(...),
    unit: str = Form(""),
    meal_label: str = Form("Breakfast"),
    logged_at: str = Form(""),
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    item = session.get(MealEntryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    meal_entry = session.get(MealEntry, item.meal_entry_id)
    if not meal_entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")

    meal_entry.meal_label = meal_label
    if logged_at:
        meal_entry.logged_at = datetime.fromisoformat(logged_at)

    item.quantity = quantity
    item.unit = unit or None
    item.quantity_text = f"{quantity:g}"

    if item.food_id:
        food = session.get(Food, item.food_id)
        if food:
            factor = serving_multiplier(quantity, item.unit, food)
            item.grams_per_serving_snapshot = multiply_value(food.grams_per_serving, factor)
            item.calories_snapshot = multiply_value(food.calories, factor) or 0.0
            item.protein_g_snapshot = multiply_value(food.protein_g, factor) or 0.0
            item.carbs_g_snapshot = multiply_value(food.carbs_g, factor) or 0.0
            item.fat_g_snapshot = multiply_value(food.fat_g, factor) or 0.0
            item.fiber_g_snapshot = multiply_value(food.fiber_g, factor)
            item.net_carbs_g_snapshot = multiply_value(food.net_carbs_g, factor)
            item.serving_description_snapshot = food.serving_description

    session.commit()
    target = redirect_to or _redirect_path_for_date(meal_entry.logged_at.date())
    return RedirectResponse(url=target, status_code=303)


@router.post("/meal-items/{item_id}/copy")
def copy_meal_item(
    item_id: int,
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    item = session.get(MealEntryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    meal_entry = session.get(MealEntry, item.meal_entry_id)
    if not meal_entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")

    session.add(
        MealEntryItem(
            meal_entry_id=item.meal_entry_id,
            food_id=item.food_id,
            parsed_phrase=item.parsed_phrase,
            normalized_phrase=item.normalized_phrase,
            quantity=item.quantity,
            unit=item.unit,
            quantity_text=item.quantity_text,
            resolution_status=item.resolution_status,
            resolution_strategy=item.resolution_strategy,
            resolution_confidence=item.resolution_confidence,
            resolved_food_name=item.resolved_food_name,
            resolved_source=item.resolved_source,
            serving_description_snapshot=item.serving_description_snapshot,
            grams_per_serving_snapshot=item.grams_per_serving_snapshot,
            calories_snapshot=item.calories_snapshot,
            protein_g_snapshot=item.protein_g_snapshot,
            carbs_g_snapshot=item.carbs_g_snapshot,
            fat_g_snapshot=item.fat_g_snapshot,
            fiber_g_snapshot=item.fiber_g_snapshot,
            net_carbs_g_snapshot=item.net_carbs_g_snapshot,
        )
    )
    session.commit()
    target = redirect_to or _redirect_path_for_date(meal_entry.logged_at.date())
    return RedirectResponse(url=target, status_code=303)


@router.post("/meal-items/{item_id}/delete")
def delete_meal_item(
    item_id: int,
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    item = session.get(MealEntryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    meal_entry = session.get(MealEntry, item.meal_entry_id)
    if not meal_entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")
    target_date = meal_entry.logged_at.date()

    session.delete(item)
    session.flush()
    remaining = session.scalar(select(MealEntryItem.id).where(MealEntryItem.meal_entry_id == meal_entry.id).limit(1))
    if remaining is None:
        session.delete(meal_entry)
    session.commit()
    target = redirect_to or _redirect_path_for_date(target_date)
    return RedirectResponse(url=target, status_code=303)


@router.post("/meals/copy")
def copy_meal_group(
    source_date: str = Form(...),
    source_meal_label: str = Form(...),
    target_date: str = Form(...),
    target_meal_label: str = Form(...),
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    source_day = date.fromisoformat(source_date)
    copy_day = date.fromisoformat(target_date)
    source_entries = _meal_entries_for_date(session, source_day, source_meal_label)
    for source_entry in source_entries:
        copied_entry = MealEntry(
            raw_input_text=source_entry.raw_input_text,
            meal_label=target_meal_label,
            logged_at=datetime.combine(copy_day, source_entry.logged_at.time()),
        )
        session.add(copied_entry)
        session.flush()
        for item in source_entry.items:
            session.add(_clone_meal_item(item, copied_entry.id))
    session.commit()
    target = redirect_to or _redirect_path_for_date(copy_day)
    return RedirectResponse(url=target, status_code=303)


@router.post("/meals/clear")
def clear_meal_group(
    source_date: str = Form(...),
    source_meal_label: str = Form(...),
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    target_day = date.fromisoformat(source_date)
    for meal_entry in _meal_entries_for_date(session, target_day, source_meal_label):
        session.delete(meal_entry)
    session.commit()
    target = redirect_to or _redirect_path_for_date(target_day)
    return RedirectResponse(url=target, status_code=303)


@router.post("/meal-items/{item_id}/move")
def move_meal_item(
    item_id: int,
    target_meal_label: str = Form(...),
    target_date: str = Form(...),
    redirect_to: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
    item = session.get(MealEntryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Meal item not found")
    source_entry = session.get(MealEntry, item.meal_entry_id)
    if not source_entry:
        raise HTTPException(status_code=404, detail="Meal entry not found")

    move_day = date.fromisoformat(target_date)
    if source_entry.logged_at.date() == move_day and source_entry.meal_label == target_meal_label:
        target = redirect_to or _redirect_path_for_date(move_day)
        return RedirectResponse(url=target, status_code=303)

    target_entry = _get_or_create_target_meal_entry(session, move_day, target_meal_label, source_entry.logged_at.time())

    if target_entry.id == source_entry.id:
        target = redirect_to or _redirect_path_for_date(move_day)
        return RedirectResponse(url=target, status_code=303)

    session.add(_clone_meal_item(item, target_entry.id))
    session.delete(item)
    session.flush()
    remaining = session.scalar(select(MealEntryItem.id).where(MealEntryItem.meal_entry_id == source_entry.id).limit(1))
    if remaining is None:
        session.delete(source_entry)
    session.commit()
    target = redirect_to or _redirect_path_for_date(move_day)
    return RedirectResponse(url=target, status_code=303)


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
