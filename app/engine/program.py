"""
Programme synthesis: client requirements -> a floor-by-floor schedule of spaces
with an area budget for each one.

This runs before any geometry. It answers "what goes on which floor and how big
should it be", so the layout solver only has to answer "where exactly".

Splitting the two stages matters: it means an infeasible brief (six bedrooms on a
60 m2 envelope) is detected here as an area deficit, and reported as a clear
error, rather than being silently squeezed into unusable rectangles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .standards import (
    CAR_BAY_WIDTH, CAR_LENGTH, STAIR_LENGTH, STAIR_WIDTH, spec,
)

# Extras the UI can switch on, mapped to the space type they create.
EXTRA_SPACES = {
    "pooja": "pooja",
    "study": "study",
    "home_office": "home_office",
    "store": "store",
    "utility": "utility",
    "guest_bedroom": "guest_bedroom",
}


@dataclass
class SpaceReq:
    """One space to be placed, with its area budget and relationships."""
    id: str
    type: str
    label: str
    floor: int
    target_area: float
    ideal_area: float
    min_area: float
    min_dim: float
    max_area: float
    zone: str
    priority: int
    habitable: bool
    wet: bool
    color: str
    fixed: bool = False              # fixed footprint (stair core, parking bay)
    fixed_w: float = 0.0
    fixed_h: float = 0.0
    attached_to: str | None = None   # e.g. an en-suite bathroom -> its bedroom
    host_id: str | None = None       # a balcony -> the room it opens off
    note: str = ""

    @property
    def flexible(self) -> bool:
        return not self.fixed


@dataclass
class FloorProgram:
    level: int
    name: str
    spaces: list[SpaceReq] = field(default_factory=list)

    @property
    def target_total(self) -> float:
        return sum(s.target_area for s in self.spaces)

    @property
    def min_total(self) -> float:
        return sum(s.min_area for s in self.spaces)


@dataclass
class Programme:
    floors: list[FloorProgram]
    balconies: list[SpaceReq]
    notes: list[str] = field(default_factory=list)
    deficits: list[dict] = field(default_factory=list)

    @property
    def all_spaces(self) -> list[SpaceReq]:
        return [s for f in self.floors for s in f.spaces]


def floor_name(level: int) -> str:
    if level == 0:
        return "Ground Floor"
    if level == 1:
        return "First Floor"
    if level == 2:
        return "Second Floor"
    if level == 3:
        return "Third Floor"
    return f"Floor {level}"


def _mk(space_type: str, floor: int, idx: int, **overrides) -> SpaceReq:
    """
    Build a SpaceReq from the standards table, with any field overridable by the
    caller. Overrides are merged rather than passed alongside the defaults so a
    caller can freely restate target_area, min_area and friends.
    """
    st = spec(space_type)
    fields = dict(
        id=f"{space_type}_{floor}_{idx}",
        type=space_type,
        label=st["label"],
        floor=floor,
        target_area=st["ideal_area"],
        ideal_area=st["ideal_area"],
        min_area=st["min_area"],
        min_dim=st["min_dim"],
        max_area=st["max_area"],
        zone=st["zone"],
        priority=st["priority"],
        habitable=st["habitable"],
        wet=st["wet"],
        color=st["color"],
    )
    fields.update({k: v for k, v in overrides.items() if v is not None})
    # Keep the ideal in step when a caller resizes a space explicitly.
    if "target_area" in overrides and "ideal_area" not in overrides:
        fields["ideal_area"] = overrides["target_area"]
    return SpaceReq(**fields)


def auto_bathroom_count(bedrooms: int, floors: int) -> int:
    """A sensible default bathroom count when the client has not specified one."""
    if bedrooms <= 1:
        return 1
    if bedrooms == 2:
        return 2
    # Master en-suite plus roughly one shared bathroom per two remaining bedrooms,
    # and never fewer than one bathroom per occupied upper floor.
    return min(bedrooms, 1 + math.ceil((bedrooms - 1) / 2) + (1 if floors >= 3 else 0))


def distribute_bedrooms(bedrooms: int, floors: int, ground_bedroom: bool) -> list[int]:
    """How many bedrooms land on each floor level."""
    per = [0] * floors
    if floors == 1:
        per[0] = bedrooms
        return per

    remaining = bedrooms
    if ground_bedroom and remaining > 0:
        per[0] = 1
        remaining -= 1

    upper = list(range(1, floors))
    i = 0
    while remaining > 0 and upper:
        per[upper[i % len(upper)]] += 1
        remaining -= 1
        i += 1
    return per


def build_programme(req: dict) -> Programme:
    """
    Turn a validated requirements dict into a Programme.

    req keys used here: floors, bedrooms, bathrooms, parking_cars, balconies,
    extras, ground_bedroom, roof_type, envelope_area, has_dining, has_living.
    """
    floors_n = int(req["floors"])
    bedrooms = int(req["bedrooms"])
    parking_cars = int(req.get("parking_cars", 0))
    balcony_n = int(req.get("balconies", 0))
    extras = list(req.get("extras", []))
    ground_bedroom = bool(req.get("ground_bedroom", False)) or floors_n == 1
    envelope_area = float(req["envelope_area"])
    roof_type = req.get("roof_type", "terrace")

    bathrooms = int(req.get("bathrooms") or 0) or auto_bathroom_count(bedrooms, floors_n)
    bed_per_floor = distribute_bedrooms(bedrooms, floors_n, ground_bedroom)

    notes: list[str] = []
    programme_floors: list[FloorProgram] = []
    balconies: list[SpaceReq] = []

    multi_storey = floors_n > 1
    bath_left = bathrooms
    master_done = False

    for lvl in range(floors_n):
        fp = FloorProgram(level=lvl, name=floor_name(lvl))
        idx = 0

        def add(space_type: str, **kw) -> SpaceReq:
            nonlocal idx
            idx += 1
            s = _mk(space_type, lvl, idx, **kw)
            fp.spaces.append(s)
            return s

        # ---- ground floor: entrance, public zone, service zone --------------
        if lvl == 0:
            # Open parking sits in the front setback and is placed by the
            # pipeline, so it never competes with rooms for envelope area.
            if parking_cars > 0 and req.get("parking_type", "covered") == "covered":
                bay_w = CAR_BAY_WIDTH * parking_cars
                add("parking",
                    label=f"Parking ({parking_cars} car{'s' if parking_cars > 1 else ''})",
                    fixed=True, fixed_w=bay_w, fixed_h=CAR_LENGTH,
                    target_area=bay_w * CAR_LENGTH,
                    min_area=CAR_WIDTH_AREA * parking_cars,
                    note=f"{parking_cars} bay(s) at {CAR_BAY_WIDTH:.2f} m x {CAR_LENGTH:.2f} m")

            add("foyer")
            if req.get("has_living", True):
                add("living")
            if req.get("has_dining", True):
                add("dining")
            add("kitchen")
            if "utility" in extras:
                add("utility")
            if "store" in extras:
                add("store")
            if "pooja" in extras:
                add("pooja")
            if "home_office" in extras:
                add("home_office")
            # A guest powder room near the entrance, once the house is big enough.
            if bedrooms >= 3 or multi_storey:
                add("toilet", label="Powder Room")

        # ---- upper floors: family space when there is room ------------------
        else:
            if lvl == 1 and bedrooms >= 3 and envelope_area >= 55:
                add("living", label="Family Lounge", target_area=14.0,
                    min_area=9.0, max_area=22.0)
            if "study" in extras and lvl == 1:
                add("study")
            if "guest_bedroom" in extras and lvl == floors_n - 1 and bed_per_floor[lvl] == 0:
                add("guest_bedroom")

        # ---- bedrooms on this floor ----------------------------------------
        n_beds_here = bed_per_floor[lvl]
        for b in range(n_beds_here):
            is_master = not master_done
            if is_master:
                bed = add("master_bedroom")
                master_done = True
                if bath_left > 0:
                    add("bathroom", label="Attached Bath", attached_to=bed.id)
                    bath_left -= 1
            else:
                add("bedroom", label=f"Bedroom {b + 1}" if n_beds_here > 1 else "Bedroom")

        # A shared bathroom on any floor that has bedrooms but no bathroom yet.
        has_bath_here = any(s.type == "bathroom" for s in fp.spaces)
        if n_beds_here > 0 and not has_bath_here and bath_left > 0:
            add("bathroom", label="Common Bath")
            bath_left -= 1

        # Spend any remaining bathroom budget on floors that carry several bedrooms.
        while bath_left > 0 and n_beds_here >= 2 and \
                sum(1 for s in fp.spaces if s.type == "bathroom") < n_beds_here:
            add("bathroom", label="Common Bath")
            bath_left -= 1

        # ---- vertical circulation -------------------------------------------
        if multi_storey:
            add("staircase", fixed=True, fixed_w=STAIR_WIDTH, fixed_h=STAIR_LENGTH,
                target_area=STAIR_WIDTH * STAIR_LENGTH,
                note="Dog-legged flight, identical footprint on every level")

        programme_floors.append(fp)

    # ---- balconies: projections, budgeted separately from the envelope ------
    if balcony_n > 0:
        hosts = _balcony_hosts(programme_floors, balcony_n)
        for n, host in enumerate(hosts, start=1):
            b = _mk("balcony", host.floor, 900 + n,
                    label=f"Balcony {n}" if len(hosts) > 1 else "Balcony")
            b.host_id = host.id
            b.note = f"Cantilevered off {host.label}"
            balconies.append(b)
        if len(hosts) < balcony_n:
            notes.append(
                f"Requested {balcony_n} balconies but only {len(hosts)} rooms have a "
                "suitable external wall; the rest were dropped."
            )

    # ---- roof level ---------------------------------------------------------
    if roof_type in ("terrace", "terrace_garden") and multi_storey:
        notes.append("Open terrace provided at roof level with a stair head room.")

    prog = Programme(floors=programme_floors, balconies=balconies, notes=notes)
    _budget_areas(prog, envelope_area)
    return prog


# Minimum legal bay area per car (clear of the bay-width comfort allowance).
CAR_WIDTH_AREA = 2.50 * 5.00


def _balcony_hosts(floors: list[FloorProgram], count: int) -> list[SpaceReq]:
    """
    Pick which rooms get balconies: upper-floor bedrooms first, then the living
    space, since those are the rooms that actually benefit from one.
    """
    ranked: list[tuple[int, SpaceReq]] = []
    for fp in floors:
        for s in fp.spaces:
            if s.type in ("master_bedroom", "bedroom", "guest_bedroom"):
                rank = 0 if fp.level > 0 else 2
            elif s.type == "living":
                rank = 1
            else:
                continue
            ranked.append((rank, s))
    ranked.sort(key=lambda t: (t[0], -t[1].priority))
    return [s for _, s in ranked[:count]]


# Rooms that can comfortably take extra floor area on a generous plot. A bigger
# plot should buy a bigger living room, not a 30 m2 kitchen.
ELASTIC_TYPES = {
    "living", "dining", "master_bedroom", "bedroom", "guest_bedroom", "study",
    "home_office",
}
ELASTIC_STRETCH = 1.65      # how far past max_area an elastic room may go
COURTYARD_THRESHOLD = 7.0   # leftover area worth turning into open space


def _absorb_residual(fp: FloorProgram, flex: list[SpaceReq], available: float) -> None:
    """
    Spend whatever envelope area the capped programme did not use.

    Without this the floor would be normalised back up uniformly, which silently
    defeats every max_area cap and produces absurd rooms on large plots. Instead
    the surplus goes first to rooms that genuinely benefit from being larger, and
    any real excess becomes an open courtyard or terrace rather than bloat.
    """
    residual = available - sum(s.target_area for s in flex)
    if residual <= 0.05:
        return

    for _ in range(8):
        growable = [s for s in flex
                    if s.type in ELASTIC_TYPES
                    and s.target_area < s.max_area * ELASTIC_STRETCH - 1e-6]
        if not growable or residual <= 0.05:
            break
        share = residual / len(growable)
        moved = 0.0
        for s in growable:
            add = min(share, s.max_area * ELASTIC_STRETCH - s.target_area)
            s.target_area += add
            moved += add
        residual -= moved
        if moved < 1e-6:
            break

    if residual > COURTYARD_THRESHOLD:
        # A deep plot with a modest brief: give the plan an open court instead of
        # inflating rooms nobody asked to be bigger.
        is_ground = fp.level == 0
        court = _mk("terrace", fp.level, 800,
                    label="Courtyard" if is_ground else "Open Terrace",
                    target_area=residual, min_area=4.0,
                    max_area=residual * 1.2,
                    note="Open to sky: absorbs the envelope area the brief does not use")
        fp.spaces.append(court)
        residual = 0.0

    if residual > 0.05:
        total = sum(s.target_area for s in flex)
        if total > 1e-6:
            k = (total + residual) / total
            for s in flex:
                s.target_area *= k


def _budget_areas(prog: Programme, envelope_area: float) -> None:
    """
    Scale each floor's flexible spaces so the programme exactly fills the
    envelope, respecting per-space minimum and maximum areas.

    Fixed spaces (stair core, parking bay) are taken off the top; whatever is
    left is shared among the flexible spaces in proportion to their ideal area.
    Any space that hits its min or max is frozen and the residual is redistributed
    over the rest, which is why this iterates.
    """
    for fp in prog.floors:
        fixed = [s for s in fp.spaces if s.fixed]
        flex = [s for s in fp.spaces if s.flexible]
        if not flex:
            continue

        fixed_area = sum(s.target_area for s in fixed)
        available = envelope_area - fixed_area

        min_needed = sum(s.min_area for s in flex)
        if available < min_needed:
            prog.deficits.append({
                "floor": fp.level,
                "floor_name": fp.name,
                "available": round(available, 2),
                "required": round(min_needed, 2),
                "shortfall": round(min_needed - available, 2),
                "spaces": len(fp.spaces),
            })
            # Still produce a layout, but at minimum sizes scaled down uniformly,
            # so the user sees exactly which rooms are being crushed.
            k = max(available, 1.0) / min_needed
            for s in flex:
                s.target_area = s.min_area * k
            continue

        frozen: dict[str, float] = {}
        for _ in range(24):
            open_spaces = [s for s in flex if s.id not in frozen]
            if not open_spaces:
                break
            rest = available - sum(frozen.values())
            ideal_sum = sum(s.ideal_area for s in open_spaces)
            if ideal_sum <= 0:
                break
            k = rest / ideal_sum
            newly_frozen = False
            for s in open_spaces:
                a = s.ideal_area * k
                if a < s.min_area - 1e-6:
                    frozen[s.id] = s.min_area
                    newly_frozen = True
                elif a > s.max_area + 1e-6:
                    frozen[s.id] = s.max_area
                    newly_frozen = True
            if not newly_frozen:
                for s in open_spaces:
                    s.target_area = s.ideal_area * k
                break

        for s in flex:
            if s.id in frozen:
                s.target_area = frozen[s.id]

        _absorb_residual(fp, flex, available)
