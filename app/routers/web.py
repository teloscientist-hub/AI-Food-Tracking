from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.foods import FoodCreate, FoodUpdate
from app.schemas.logging import LogMealRequest, LogReviewItem
from app.services.food_service import (
    create_food,
    food_to_read,
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


@router.get("/")
def dashboard(
    request: Request,
    metric: str = "calories",
    session: Session = Depends(get_session),
) -> object:
    today = date.today()
    summary_service = SummaryService()
    daily = summary_service.get_daily_summary(session, today)
    weekly = summary_service.get_weekly_summary(session, today, metric)
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


@router.get("/log")
def add_log_entry(request: Request) -> object:
    return templates.TemplateResponse(request, "add_log.html", {"today": datetime.now().isoformat(timespec="minutes")})


@router.post("/log/review")
def review_log_entry(
    request: Request,
    raw_input_text: str = Form(...),
    meal_label: str = Form("General"),
    logged_at: str = Form(""),
    session: Session = Depends(get_session),
) -> object:
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
        if not selection:
            raise HTTPException(status_code=400, detail="Each line item needs a selected food")

        if selection.startswith("food:"):
            selected_food_id = int(selection.split(":", 1)[1])
        elif selection.startswith("external:"):
            candidate_index = int(selection.split(":", 1)[1])
            imported = service.persist_external_candidate(session, candidate_index, candidate_groups[index])
            selected_food_id = imported.id
        else:
            raise HTTPException(status_code=400, detail="Unknown food selection type")

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
    foods = [food_to_read(session, food) for food in search_foods(session, q, source)]
    return templates.TemplateResponse(
        request,
        "foods_library.html",
        {"foods": foods, "q": q or "", "source": source},
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
        {"food": food_to_read(session, food)},
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
