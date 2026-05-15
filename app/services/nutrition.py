from __future__ import annotations


def derive_net_carbs(
    carbs_g: float | None,
    fiber_g: float | None = None,
    net_carbs_g: float | None = None,
) -> float:
    if net_carbs_g is not None:
        return round(float(net_carbs_g), 2)
    carbs = float(carbs_g or 0.0)
    fiber = float(fiber_g or 0.0)
    return round(max(carbs - fiber, 0.0), 2)


def item_net_carbs(item: object) -> float:
    return derive_net_carbs(
        getattr(item, "carbs_g_snapshot", 0.0),
        getattr(item, "fiber_g_snapshot", None),
        getattr(item, "net_carbs_g_snapshot", None),
    )


def food_net_carbs(food: object) -> float:
    return derive_net_carbs(
        getattr(food, "carbs_g", 0.0),
        getattr(food, "fiber_g", None),
        getattr(food, "net_carbs_g", None),
    )
