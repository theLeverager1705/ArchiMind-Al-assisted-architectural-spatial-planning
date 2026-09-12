"""
Indicative construction cost.

The brief asks for an estimate that is transparent and explainable, so nothing
here is a lump-sum rate per square foot. Every line item names the quantity it
was driven by, the rate applied and the arithmetic, and the whole table is
recomputed from the plan's real measured quantities: wall runs come from the
extracted wall network, opening counts from the actual doors and windows, wet
points from the rooms that have plumbing.

Rates are indicative 2026 assumptions for an Indian Tier-2 city and are exposed
so a user can override them.
"""

from __future__ import annotations

from .standards import (
    CITY_FACTOR, CITY_LABEL, COST_ITEMS, COST_PERCENT_ITEMS,
    QUALITY_FACTOR, QUALITY_LABEL,
)


def _driver_value(driver: str, m: dict) -> tuple[float, str]:
    """Resolve a cost driver to a measured quantity plus a human description."""
    if driver == "footprint_area":
        return m["footprint_area"], f"{m['footprint_area']:.1f} m2 ground floor footprint"
    if driver == "builtup_area":
        return m["weighted_area"], (
            f"{m['weighted_area']:.1f} m2 weighted built-up "
            f"(open areas counted at a reduced rate)")
    if driver == "wall_area":
        return m["wall_area"], (
            f"{m['wall_run']:.1f} m of wall x 2 faces x 2.90 m = {m['wall_area']:.1f} m2")
    if driver == "opening_count":
        return float(m["opening_count"]), (
            f"{m['door_count']} doors + {m['window_count']} windows")
    if driver == "wet_room_count":
        return float(m["wet_room_count"]), f"{m['wet_room_count']} bathrooms, kitchens and utilities"
    if driver == "roof_area":
        return m["roof_area"], f"{m['roof_area']:.1f} m2 terrace slab"
    if driver == "site_work_area":
        return m["site_work_area"], f"{m['site_work_area']:.1f} m2 of open plot"
    return 0.0, ""


def estimate(metrics: dict, quality: str = "standard", city_tier: str = "tier2",
             rate_overrides: dict | None = None) -> dict:
    """
    Build the full cost breakdown.

    Returns measured quantities, per-item arithmetic, percentage add-ons and a
    set of headline figures, all in one structure the UI can render as a table.
    """
    qf = QUALITY_FACTOR.get(quality, 1.0)
    cf = CITY_FACTOR.get(city_tier, 1.0)
    factor = qf * cf
    overrides = rate_overrides or {}

    items: list[dict] = []
    direct_total = 0.0

    for spec_item in COST_ITEMS:
        qty, basis = _driver_value(spec_item["driver"], metrics)
        base_rate = float(overrides.get(spec_item["key"], spec_item["rate"]))
        # Finishes and fittings scale with specification; structure barely does.
        scales_with_quality = spec_item["key"] not in ("earthwork", "foundation", "structure")
        applied_rate = base_rate * (factor if scales_with_quality else cf)
        amount = qty * applied_rate
        direct_total += amount
        items.append({
            "key": spec_item["key"],
            "label": spec_item["label"],
            "driver": spec_item["driver"],
            "basis": basis,
            "quantity": round(qty, 2),
            "unit": spec_item["unit"],
            "base_rate": round(base_rate, 2),
            "applied_rate": round(applied_rate, 2),
            "amount": round(amount, 2),
            "formula": f"{qty:,.2f} x Rs {applied_rate:,.0f}",
            "note": spec_item["note"],
        })

    addons: list[dict] = []
    addon_total = 0.0
    for pct_item in COST_PERCENT_ITEMS:
        amount = direct_total * pct_item["pct"]
        addon_total += amount
        addons.append({
            "key": pct_item["key"],
            "label": pct_item["label"],
            "pct": pct_item["pct"],
            "amount": round(amount, 2),
            "formula": f"{pct_item['pct'] * 100:.1f}% of Rs {direct_total:,.0f}",
            "note": pct_item["note"],
        })

    grand = direct_total + addon_total
    builtup = max(metrics["builtup_area"], 1e-6)
    builtup_sqft = max(metrics["builtup_area_sqft"], 1e-6)

    return {
        "currency": "INR",
        "quality": quality,
        "quality_label": QUALITY_LABEL.get(quality, quality),
        "city_tier": city_tier,
        "city_label": CITY_LABEL.get(city_tier, city_tier),
        "quality_factor": qf,
        "city_factor": cf,
        "items": items,
        "addons": addons,
        "direct_total": round(direct_total, 2),
        "addon_total": round(addon_total, 2),
        "grand_total": round(grand, 2),
        "per_sqm": round(grand / builtup, 2),
        "per_sqft": round(grand / builtup_sqft, 2),
        "range_low": round(grand * 0.90, 2),
        "range_high": round(grand * 1.15, 2),
        "assumptions": [
            f"Rates are indicative for a {CITY_LABEL.get(city_tier, city_tier)} at "
            f"{QUALITY_LABEL.get(quality, quality).lower()} specification.",
            "Quantities are measured from the generated plan, not assumed from a "
            "per-square-foot rule of thumb.",
            "Structure and foundation rates scale with location only; finishes, "
            "fittings and services also scale with the chosen specification.",
            "Open areas are billed at a reduced weight: parking 42%, balcony 55%, "
            "terrace 30% of an enclosed square metre.",
            "Excludes land cost, boundary wall beyond the plot frontage share, "
            "furniture, and any statutory deposit refundable on completion.",
            "Shown as a range of -10% to +15% to reflect rate volatility.",
        ],
    }
