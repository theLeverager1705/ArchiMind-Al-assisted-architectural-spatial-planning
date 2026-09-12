"""
Area accounting for a generated plan.

One module owns every derived quantity so the validator, the cost model and the
UI can never disagree about how big the building is. Indian practice separates
several different "areas" and they are not interchangeable, so each is computed
explicitly rather than approximated from the others.
"""

from __future__ import annotations

from .geometry import Rect
from .standards import (
    AREA_WEIGHT, CEILING_HEIGHT, WALL_EXTERIOR, WALL_INTERIOR,
)

# Spaces that are unroofed and therefore excluded from enclosed floor area.
OPEN_AREA_TYPES = {"balcony", "terrace"}
# Parking is enclosed but is normally exempt from the FAR calculation.
FAR_EXEMPT_TYPES = {"parking"}


def _carpet(rect: Rect) -> float:
    """
    Clear floor area inside the finished walls.

    Rooms are modelled to wall centrelines, so the carpet area is the rectangle
    shrunk by half a wall on each side.
    """
    t = WALL_INTERIOR
    return max(0.0, (rect.w - t) * (rect.h - t))


def compute_metrics(rooms: list, walls: list, openings: list,
                    plot: Rect, envelope: Rect, floors: int) -> dict:
    levels = sorted({r.floor for r in rooms}) or [0]

    per_floor: list[dict] = []
    for lvl in levels:
        fr = [r for r in rooms if r.floor == lvl]
        enclosed = sum(r.rect.area for r in fr if r.type not in OPEN_AREA_TYPES)
        open_area = sum(r.rect.area for r in fr if r.type in OPEN_AREA_TYPES)
        carpet = sum(_carpet(r.rect) for r in fr if r.type not in OPEN_AREA_TYPES)
        far_area = sum(r.rect.area for r in fr
                       if r.type not in OPEN_AREA_TYPES and r.type not in FAR_EXEMPT_TYPES)
        per_floor.append({
            "level": lvl,
            "enclosed_area": round(enclosed, 2),
            "open_area": round(open_area, 2),
            "carpet_area": round(carpet, 2),
            "far_area": round(far_area, 2),
            "rooms": len(fr),
        })

    builtup = sum(f["enclosed_area"] for f in per_floor)
    carpet_total = sum(f["carpet_area"] for f in per_floor)
    far_total = sum(f["far_area"] for f in per_floor)
    open_total = sum(f["open_area"] for f in per_floor)

    ground = [r for r in rooms if r.floor == 0]
    footprint = sum(r.rect.area for r in ground if r.type not in OPEN_AREA_TYPES)

    # Weighted area is what the cost model bills: an open balcony or a parking
    # slab does not cost the same per square metre as an enclosed room.
    weighted = 0.0
    for r in rooms:
        weighted += r.rect.area * AREA_WEIGHT.get(r.type, 1.0)

    wall_run = sum(w.length for w in walls)
    wall_face = wall_run * CEILING_HEIGHT * 2.0

    doors = [o for o in openings if o.kind in ("door", "main_door", "opening")]
    windows = [o for o in openings if o.kind == "window"]
    wet_rooms = [r for r in rooms if getattr(r, "wet", False)]

    top_level = max(levels)
    roof_area = sum(r.rect.area for r in rooms
                    if r.floor == top_level and r.type not in OPEN_AREA_TYPES)

    plot_area = plot.area
    return {
        "plot_area": round(plot_area, 2),
        "plot_area_sqft": round(plot_area * 10.7639, 1),
        "envelope_area": round(envelope.area, 2),
        "floors": floors,
        "per_floor": per_floor,
        "footprint_area": round(footprint, 2),
        "builtup_area": round(builtup, 2),
        "builtup_area_sqft": round(builtup * 10.7639, 1),
        "carpet_area": round(carpet_total, 2),
        "carpet_area_sqft": round(carpet_total * 10.7639, 1),
        "far_area": round(far_total, 2),
        "open_area": round(open_total, 2),
        "weighted_area": round(weighted, 2),
        "roof_area": round(roof_area, 2),
        "site_work_area": round(max(0.0, plot_area - footprint), 2),
        "wall_run": round(wall_run, 2),
        "wall_area": round(wall_face, 2),
        "door_count": len(doors),
        "window_count": len(windows),
        "opening_count": len(doors) + len(windows),
        "wet_room_count": len(wet_rooms),
        "room_count": len(rooms),
        "coverage": round(footprint / plot_area, 4) if plot_area else 0.0,
        "far": round(far_total / plot_area, 4) if plot_area else 0.0,
        "efficiency": round(carpet_total / builtup, 4) if builtup else 0.0,
        "open_space": round(max(0.0, plot_area - footprint) / plot_area, 4) if plot_area else 0.0,
        "wall_thickness": {"exterior": WALL_EXTERIOR, "interior": WALL_INTERIOR},
    }
