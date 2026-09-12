"""
The planning pipeline.

Requirements in, complete plan out:

    normalise -> programme -> solve layout -> parking & balconies ->
    doors, windows, walls -> furniture -> metrics -> validate -> cost

Everything the 2D drawing, the 3D model, the validation panel and the cost table
need comes out of this one call, derived from a single set of rectangles. That is
what keeps the 3D view consistent with the 2D plan: they are not two models, they
are two renderings of the same data.
"""

from __future__ import annotations

import time

from .cost import estimate
from .furniture import furnish
from .geometry import Rect
from .layout import place_balconies, solve
from .metrics import compute_metrics
from .program import build_programme, floor_name
from .standards import (
    CAR_BAY_WIDTH, CAR_LENGTH, CEILING_HEIGHT, FLOOR_TO_FLOOR, PARAPET_HEIGHT,
    SLAB_THICKNESS, WALL_EXTERIOR, WALL_INTERIOR, ZONE_COLOR, ZONE_LABEL, spec,
)
from .topology import (
    build_contacts, extract_walls, place_doors, place_windows, reachability_report,
)
from .validate import max_coverage_for, validate

FT_TO_M = 0.3048

VALID_EXTRAS = {"pooja", "study", "home_office", "store", "utility", "guest_bedroom"}
VALID_ROOFS = {"flat", "terrace", "sloped", "terrace_garden"}
VALID_QUALITY = {"economy", "standard", "premium", "luxury"}
VALID_TIER = {"tier1", "tier2", "tier3"}
VALID_PARKING = {"covered", "open"}
VALID_FACING = {"N", "E", "S", "W"}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _num(value, default: float) -> float:
    try:
        f = float(value)
        return f if f == f and abs(f) != float("inf") else default
    except (TypeError, ValueError):
        return default


def normalise(raw: dict) -> dict:
    """
    Coerce and clamp whatever arrived from the UI or the AI into a safe brief.

    The AI path shares this function, which is the point: model output is treated
    as untrusted input and is bounded here before it can reach the solver.
    """
    units = raw.get("units", "ft")
    units = units if units in ("ft", "m") else "ft"
    k = FT_TO_M if units == "ft" else 1.0

    pw = _clamp(_num(raw.get("plot_width"), 30 if units == "ft" else 9.0) * k, 3.0, 120.0)
    pd = _clamp(_num(raw.get("plot_depth"), 40 if units == "ft" else 12.0) * k, 3.0, 150.0)

    # Setbacks are always entered in metres: they are regulatory dimensions.
    sf = _clamp(_num(raw.get("setback_front"), 1.5), 0.0, pd / 2 - 0.5)
    sr = _clamp(_num(raw.get("setback_rear"), 1.0), 0.0, pd / 2 - 0.5)
    sl = _clamp(_num(raw.get("setback_left"), 0.9), 0.0, pw / 2 - 0.5)
    sg = _clamp(_num(raw.get("setback_right"), 0.9), 0.0, pw / 2 - 0.5)

    extras = [e for e in (raw.get("extras") or []) if e in VALID_EXTRAS]

    return {
        "units": units,
        "plot_width": round(pw, 3),
        "plot_depth": round(pd, 3),
        "plot_width_input": round(pw / k, 2),
        "plot_depth_input": round(pd / k, 2),
        "setback_front": round(sf, 3),
        "setback_rear": round(sr, 3),
        "setback_left": round(sl, 3),
        "setback_right": round(sg, 3),
        "floors": int(_clamp(_num(raw.get("floors"), 2), 1, 4)),
        "bedrooms": int(_clamp(_num(raw.get("bedrooms"), 3), 0, 8)),
        "bathrooms": int(_clamp(_num(raw.get("bathrooms"), 0), 0, 8)),
        "parking_cars": int(_clamp(_num(raw.get("parking_cars"), 1), 0, 4)),
        "parking_type": raw.get("parking_type") if raw.get("parking_type") in VALID_PARKING else "covered",
        "balconies": int(_clamp(_num(raw.get("balconies"), 1), 0, 6)),
        "roof_type": raw.get("roof_type") if raw.get("roof_type") in VALID_ROOFS else "terrace",
        "extras": extras,
        "ground_bedroom": bool(raw.get("ground_bedroom", False)),
        "has_living": bool(raw.get("has_living", True)),
        "has_dining": bool(raw.get("has_dining", True)),
        "facing": raw.get("facing") if raw.get("facing") in VALID_FACING else "N",
        "quality": raw.get("quality") if raw.get("quality") in VALID_QUALITY else "standard",
        "city_tier": raw.get("city_tier") if raw.get("city_tier") in VALID_TIER else "tier2",
        "max_far": _clamp(_num(raw.get("max_far"), 2.0), 0.5, 6.0),
        "max_coverage": _coverage_input(raw.get("max_coverage")),
        "restarts": int(_clamp(_num(raw.get("restarts"), 500), 40, 900)),
        "notes": str(raw.get("notes") or "")[:2000],
    }


def _coverage_input(value) -> float:
    """0 means "decide from the plot size"; anything else is the client's own cap."""
    v = _num(value, 0.0)
    return _clamp(v, 0.2, 0.95) if v > 0 else 0.0


def _place_open_parking(req: dict, plot: Rect, rooms: list) -> list:
    """
    Put an open parking bay in the front setback.

    This is how parking usually works on an Indian residential plot: the car
    stands in the mandatory front open space rather than eating into the
    buildable envelope, and it is normally exempt from FAR.
    """
    from .layout import PlacedRoom

    cars = req["parking_cars"]
    if cars <= 0 or req["parking_type"] != "open":
        return []

    band_depth = req["setback_front"]
    if band_depth < 0.5:
        return []

    # Nose-in first (cars perpendicular to the street), otherwise parallel.
    options = [
        (CAR_BAY_WIDTH * cars, min(CAR_LENGTH, band_depth), "nose-in"),
        (CAR_LENGTH * cars, min(CAR_BAY_WIDTH, band_depth), "parallel"),
    ]
    for w, h, mode in options:
        if w <= plot.w - 0.2 and h >= CAR_BAY_WIDTH - 0.05 and h <= band_depth + 1e-6:
            if mode == "nose-in" and h < CAR_LENGTH - 0.6:
                continue
            # Sit the bay on the side of the frontage nearest the entrance.
            foyer = next((r for r in rooms if r.type == "foyer" and r.floor == 0), None)
            left = True if foyer is None else foyer.rect.cx <= plot.cx
            x = 0.1 if left else plot.w - w - 0.1
            rect = Rect(x, max(0.0, band_depth - h), w, h).snapped()
            st = spec("parking")
            return [PlacedRoom(
                id="parking_open", type="parking",
                label=f"Open Parking ({cars} car{'s' if cars > 1 else ''})",
                floor=0, rect=rect, zone=st["zone"], color=st["color"],
                priority=st["priority"], habitable=False, wet=False,
                target_area=rect.area, min_area=st["min_area"], min_dim=st["min_dim"],
                max_area=st["max_area"], aspect_max=st["aspect_max"],
                note=f"{mode} bay in the front setback, exempt from FAR",
            )]
    return []


def generate_plan(raw: dict) -> dict:
    t0 = time.perf_counter()
    req = normalise(raw)

    plot = Rect(0.0, 0.0, req["plot_width"], req["plot_depth"]).snapped()
    # Resolve the coverage cap now so every consumer - validator, UI, report -
    # sees the same effective number rather than a sentinel.
    if req["max_coverage"] <= 0:
        req["max_coverage"] = max_coverage_for(plot.area)
    envelope = Rect(
        req["setback_left"],
        req["setback_front"],
        max(0.5, plot.w - req["setback_left"] - req["setback_right"]),
        max(0.5, plot.h - req["setback_front"] - req["setback_rear"]),
    ).snapped()

    # ---- programme ---------------------------------------------------------
    prog_input = dict(req)
    prog_input["envelope_area"] = envelope.area
    programme = build_programme(prog_input)

    # ---- layout ------------------------------------------------------------
    cand = solve(programme, envelope, restarts=req["restarts"])
    rooms = list(cand.rooms)

    # ---- parking and balconies ---------------------------------------------
    rooms.extend(_place_open_parking(req, plot, rooms))
    balconies, balcony_notes = place_balconies(
        programme.balconies, rooms, envelope,
        dict(front=req["setback_front"], rear=req["setback_rear"],
             left=req["setback_left"], right=req["setback_right"]),
    )
    programme.notes.extend(balcony_notes)

    # ---- openings, walls, furniture ----------------------------------------
    # Balconies join the room set before doors are placed: a balcony needs a
    # door off its host room, and must count as reachable like any other space.
    rooms.extend(balconies)
    interior = [r for r in rooms if r.id != "parking_open"]
    contacts = build_contacts(interior)
    doors = place_doors(interior, contacts, envelope)
    windows = place_windows(interior, envelope, doors)
    openings = doors + windows
    walls = extract_walls(interior, envelope)

    all_rooms = rooms
    furniture = furnish(all_rooms, doors)
    reach = reachability_report(interior, doors)

    # ---- metrics, validation, cost -----------------------------------------
    metrics = compute_metrics(all_rooms, walls, openings, plot, envelope, req["floors"])
    report = validate(all_rooms, walls, openings, plot, envelope, req, metrics, programme)
    costing = estimate(metrics, req["quality"], req["city_tier"],
                       raw.get("rate_overrides") or None)

    # ---- assemble ----------------------------------------------------------
    levels = []
    for lvl in range(req["floors"]):
        lr = [r for r in all_rooms if r.floor == lvl]
        levels.append({
            "level": lvl,
            "name": floor_name(lvl),
            "base_height": round(lvl * FLOOR_TO_FLOOR, 3),
            "rooms": len(lr),
            "area": round(sum(r.rect.area for r in lr), 2),
            "reachable": reach.get(lvl, {}).get("ratio", 1.0),
        })

    elapsed = (time.perf_counter() - t0) * 1000.0

    return {
        "ok": True,
        "requirements": req,
        "plot": plot.as_dict(),
        "envelope": envelope.as_dict(),
        "setbacks": {
            "front": req["setback_front"], "rear": req["setback_rear"],
            "left": req["setback_left"], "right": req["setback_right"],
        },
        "levels": levels,
        "rooms": [r.as_dict() for r in all_rooms],
        "walls": [w.as_dict() for w in walls],
        "openings": [o.as_dict() for o in openings],
        "furniture": [f.as_dict() for f in furniture],
        "contacts": [c.as_dict() for c in contacts],
        "metrics": metrics,
        "validation": report,
        "cost": costing,
        "score": {
            "total": round(cand.score * 100, 1),
            "parts": {k: round(v * 100, 1) for k, v in cand.breakdown["parts"].items()},
            "weights": cand.breakdown["weights"],
            "seed": cand.seed,
        },
        "relationships": cand.breakdown["relationships"],
        "programme_notes": programme.notes,
        "constants": {
            "floor_to_floor": FLOOR_TO_FLOOR,
            "ceiling_height": CEILING_HEIGHT,
            "slab": SLAB_THICKNESS,
            "wall_exterior": WALL_EXTERIOR,
            "wall_interior": WALL_INTERIOR,
            "parapet": PARAPET_HEIGHT,
        },
        "legend": {
            "zones": [{"key": k, "label": v, "color": ZONE_COLOR[k]} for k, v in ZONE_LABEL.items()],
        },
        "timing_ms": round(elapsed, 1),
    }
