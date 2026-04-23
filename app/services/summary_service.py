from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DailyNote, DailyTarget, Food, FoodResolutionHistory, MealEntry, MealEntryItem


class SummaryService:
    def _resolve_target(self, session: Session, target_date: date) -> DailyTarget | None:
        target = session.scalar(select(DailyTarget).where(DailyTarget.target_date == target_date))
        if target:
            return target
        return session.scalar(select(DailyTarget).order_by(DailyTarget.target_date.desc()).limit(1))

    def get_daily_summary(self, session: Session, target_date: date) -> dict:
        start_dt = datetime.combine(target_date, time.min)
        end_dt = datetime.combine(target_date, time.max)

        items = session.scalars(
            select(MealEntryItem)
            .join(MealEntry)
            .where(MealEntry.logged_at >= start_dt, MealEntry.logged_at <= end_dt)
        ).all()
        totals = {
            "calories": round(sum(item.calories_snapshot for item in items), 2),
            "protein": round(sum(item.protein_g_snapshot for item in items), 2),
            "carbs": round(sum(item.carbs_g_snapshot for item in items), 2),
            "fat": round(sum(item.fat_g_snapshot for item in items), 2),
            "fiber": round(sum(item.fiber_g_snapshot or 0.0 for item in items), 2),
            "net_carbs": round(sum(item.net_carbs_g_snapshot or 0.0 for item in items), 2),
        }
        target = self._resolve_target(session, target_date)
        last_entry = session.scalar(
            select(MealEntry).order_by(MealEntry.logged_at.desc()).limit(1)
        )

        streak_days = 0
        check_date = target_date
        while True:
            day_start = datetime.combine(check_date, time.min)
            day_end = datetime.combine(check_date, time.max)
            has_entry = session.scalar(
                select(MealEntry.id)
                .where(MealEntry.logged_at >= day_start, MealEntry.logged_at <= day_end)
                .limit(1)
            )
            if not has_entry:
                break
            streak_days += 1
            check_date -= timedelta(days=1)

        status_text = "No target configured"
        if target:
            delta = totals["calories"] - target.calories_target
            if abs(delta) <= max(target.calories_target * 0.1, 100):
                status_text = "On target"
            elif delta > 0:
                status_text = "Over target"
            else:
                status_text = "Under target"

        def pack(consumed: float, target_value: float | None) -> dict:
            return {
                "consumed": consumed,
                "remaining": round((target_value or 0.0) - consumed, 2) if target_value is not None else 0.0,
                "target": target_value,
            }

        return {
            "date": target_date.isoformat(),
            "calories": pack(totals["calories"], target.calories_target if target else None),
            "protein": pack(totals["protein"], target.protein_target_g if target else None),
            "carbs": pack(totals["carbs"], target.carbs_target_g if target else None),
            "fat": pack(totals["fat"], target.fat_target_g if target else None),
            "fiber": pack(totals["fiber"], target.fiber_target_g if target and target.fiber_target_g is not None else None),
            "net_carbs": pack(
                totals["net_carbs"],
                target.net_carbs_target_g if target and target.net_carbs_target_g is not None else None,
            ),
            "streak_days": streak_days,
            "last_logged_at": last_entry.logged_at.isoformat() if last_entry else None,
            "status_text": status_text,
        }

    def get_weekly_summary(self, session: Session, end_date: date, metric: str = "calories") -> dict:
        days: list[dict] = []
        start_date = end_date - timedelta(days=6)
        adherence_days = 0
        top_foods: defaultdict[str, float] = defaultdict(float)

        for offset in range(7):
            current_day = start_date + timedelta(days=offset)
            summary = self.get_daily_summary(session, current_day)
            days.append(
                {
                    "day": current_day.strftime("%a"),
                    "calories": summary["calories"]["consumed"],
                    "protein_g": summary["protein"]["consumed"],
                    "carbs_g": summary["carbs"]["consumed"],
                    "fat_g": summary["fat"]["consumed"],
                    "fiber_g": summary["fiber"]["consumed"] if summary["fiber"] else 0.0,
                    "net_carbs_g": summary["net_carbs"]["consumed"] if summary["net_carbs"] else 0.0,
                }
            )
            if summary["status_text"] == "On target":
                adherence_days += 1

        top_rows = session.execute(
            select(MealEntryItem.resolved_food_name, func.sum(MealEntryItem.protein_g_snapshot))
            .join(MealEntry)
            .where(
                MealEntry.logged_at >= datetime.combine(start_date, time.min),
                MealEntry.logged_at <= datetime.combine(end_date, time.max),
            )
            .group_by(MealEntryItem.resolved_food_name)
            .order_by(func.sum(MealEntryItem.protein_g_snapshot).desc())
            .limit(5)
        ).all()
        for name, total in top_rows:
            if name:
                top_foods[name] = round(float(total), 2)

        averages = {
            "calories": round(sum(day["calories"] for day in days) / 7, 2),
            "protein_g": round(sum(day["protein_g"] for day in days) / 7, 2),
            "carbs_g": round(sum(day["carbs_g"] for day in days) / 7, 2),
            "fat_g": round(sum(day["fat_g"] for day in days) / 7, 2),
        }
        return {
            "metric": metric,
            "days": days,
            "averages": averages,
            "top_foods": [{"name": name, "value": value} for name, value in top_foods.items()],
            "adherence_days": adherence_days,
        }

    def get_daily_log(self, session: Session, target_date: date) -> list[MealEntry]:
        start_dt = datetime.combine(target_date, time.min)
        end_dt = datetime.combine(target_date, time.max)
        return session.scalars(
            select(MealEntry)
            .where(MealEntry.logged_at >= start_dt, MealEntry.logged_at <= end_dt)
            .order_by(MealEntry.logged_at.asc())
        ).all()

    def get_daily_note(self, session: Session, target_date: date) -> str:
        note = session.scalar(select(DailyNote).where(DailyNote.note_date == target_date))
        return note.body if note else ""

    def save_daily_note(self, session: Session, target_date: date, body: str) -> None:
        note = session.scalar(select(DailyNote).where(DailyNote.note_date == target_date))
        if note:
            note.body = body.strip()
        else:
            session.add(DailyNote(note_date=target_date, body=body.strip()))
        session.commit()

    def get_dashboard_context(self, session: Session, target_date: date) -> dict:
        custom_food_count = session.scalar(
            select(func.count()).select_from(Food).where(Food.source == "custom", Food.is_current.is_(True))
        ) or 0
        remembered_phrases = session.scalar(
            select(func.count()).select_from(FoodResolutionHistory).where(
                FoodResolutionHistory.action_taken == "confirm"
            )
        ) or 0
        unresolved_count = session.scalar(
            select(func.count()).select_from(MealEntryItem).where(MealEntryItem.resolution_status != "resolved")
        ) or 0
        note_body = self.get_daily_note(session, target_date)
        return {
            "custom_food_count": int(custom_food_count),
            "remembered_phrases": int(remembered_phrases),
            "unresolved_count": int(unresolved_count),
            "daily_note": note_body,
        }
