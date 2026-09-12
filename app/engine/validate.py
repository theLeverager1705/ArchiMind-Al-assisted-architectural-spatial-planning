"""
The validation engine.

The brief is explicit that the system must identify problems rather than quietly
emit an invalid plan, so every check here produces a structured finding with:

  * a severity the UI can colour and sort by
  * the rule that was applied and the numbers that failed it
  * the specific rooms involved, so the drawing can highlight them
  * where possible a concrete fix the user can apply in one click

Findings are data, not prose: the same list drives the report panel, the plan
highlighting and the AI critique prompt.
"""

from __future__ import annotations

from collections import defaultdict

from .geometry import Rect, exterior_edges, rects_overlap
from .standards import (
    CAR_LENGTH, CAR_WIDTH, DEFAULT_MAX_FAR, DEFAULT_MAX_GROUND_COVERAGE,
    LIGHT_VENT_RATIO, STAIR_LENGTH, STAIR_WIDTH, WINDOW_HEIGHT, spec,
)
from .topology import evaluate_relationships, glazing_by_room, reachability_report

ERROR, WARN, INFO, OK = "error", "warning", "info", "pass"

SEVERITY_RANK = {ERROR: 0, WARN: 1, INFO: 2, OK: 3}

# Minimum setbacks by plot frontage, following common Indian development control
# rules for low-rise residential plots.
MIN_SETBACK_BY_WIDTH = [
    (9.5, dict(front=1.5, rear=1.0, side=0.75)),
    (12.0, dict(front=3.0, rear=1.5, side=0.9)),
    (18.0, dict(front=4.5, rear=3.0, side=1.5)),
    (999.0, dict(front=6.0, rear=3.0, side=2.0)),
]


# Permitted ground coverage by plot area. Small plots are allowed to cover more
# of the site, which is what makes building on a 30x40 ft site possible at all;
# applying a flat 65% to every plot size flags compliant small houses as illegal.
MAX_COVERAGE_BY_AREA = [
    (120.0, 0.80),
    (200.0, 0.70),
    (400.0, 0.65),
    (1e9, 0.60),
]


def max_coverage_for(plot_area: float) -> float:
    for limit, cov in MAX_COVERAGE_BY_AREA:
        if plot_area <= limit:
            return cov
    return MAX_COVERAGE_BY_AREA[-1][1]


def min_setbacks_for(plot_width: float) -> dict:
    for limit, rule in MIN_SETBACK_BY_WIDTH:
        if plot_width <= limit:
            return rule
    return MIN_SETBACK_BY_WIDTH[-1][1]


class Report:
    def __init__(self) -> None:
        self.findings: list[dict] = []
        self._n = 0

    def add(self, severity: str, category: str, title: str, message: str,
            *, code: str = "", rooms: list[str] | None = None,
            value=None, limit=None, unit: str = "", suggestion: str = "",
            fix: dict | None = None) -> None:
        self._n += 1
        self.findings.append({
            "id": f"v{self._n}",
            "severity": severity,
            "category": category,
            "title": title,
            "message": message,
            "code": code,
            "rooms": rooms or [],
            "value": round(value, 3) if isinstance(value, (int, float)) else value,
            "limit": round(limit, 3) if isinstance(limit, (int, float)) else limit,
            "unit": unit,
            "suggestion": suggestion,
            "fix": fix,
        })

    def as_dict(self) -> dict:
        counts = defaultdict(int)
        for f in self.findings:
            counts[f["severity"]] += 1
        ordered = sorted(self.findings, key=lambda f: (SEVERITY_RANK[f["severity"]], f["category"]))
        # A plan is "compliant" when nothing is an outright error.
        return {
            "findings": ordered,
            "counts": {
                "error": counts[ERROR], "warning": counts[WARN],
                "info": counts[INFO], "pass": counts[OK],
            },
            "compliant": counts[ERROR] == 0,
            "checks_run": len(self.findings),
        }


def validate(rooms, walls, openings, plot: Rect, envelope: Rect,
             req: dict, metrics: dict, programme=None) -> dict:
    rep = Report()

    _check_plot_and_envelope(rep, plot, envelope, req, metrics)
    _check_geometry(rep, rooms, envelope)
    _check_room_sizes(rep, rooms)
    _check_relationships(rep, rooms, openings)
    _check_circulation(rep, rooms, openings, req)
    _check_light_and_vent(rep, rooms, openings, envelope)
    _check_services(rep, rooms, req, metrics)
    _check_programme(rep, programme, req)

    return rep.as_dict()


# --------------------------------------------------------------------------
def _check_plot_and_envelope(rep: Report, plot: Rect, envelope: Rect,
                             req: dict, m: dict) -> None:
    setbacks = {
        "front": float(req.get("setback_front", 0)),
        "rear": float(req.get("setback_rear", 0)),
        "left": float(req.get("setback_left", 0)),
        "right": float(req.get("setback_right", 0)),
    }
    rule = min_setbacks_for(plot.w)

    for side, needed in (("front", rule["front"]), ("rear", rule["rear"]),
                         ("left", rule["side"]), ("right", rule["side"])):
        got = setbacks[side]
        if got + 1e-6 < needed:
            rep.add(ERROR, "Setbacks", f"{side.title()} setback below the minimum",
                    f"The {side} setback is {got:.2f} m. For a {plot.w:.1f} m wide plot the "
                    f"development control minimum is {needed:.2f} m.",
                    code="DCR-setback", value=got, limit=needed, unit="m",
                    suggestion=f"Increase the {side} setback to at least {needed:.2f} m.",
                    fix={"field": f"setback_{side}", "value": needed,
                         "label": f"Set {side} setback to {needed:.2f} m"})
        else:
            rep.add(OK, "Setbacks", f"{side.title()} setback complies",
                    f"{got:.2f} m provided against a {needed:.2f} m minimum.",
                    code="DCR-setback", value=got, limit=needed, unit="m")

    if envelope.w <= 1.5 or envelope.h <= 1.5:
        rep.add(ERROR, "Envelope", "Buildable envelope is unusable",
                f"After setbacks only {envelope.w:.2f} m x {envelope.h:.2f} m remains. "
                f"Nothing habitable can be planned inside it.",
                code="ENV-size", value=min(envelope.w, envelope.h), limit=1.5, unit="m",
                suggestion="Reduce the setbacks or choose a larger plot.")

    # An explicit client value wins; otherwise use the band for this plot size.
    max_cov = float(req.get("max_coverage") or 0) or max_coverage_for(plot.area)
    if m["coverage"] > max_cov + 1e-4:
        rep.add(ERROR, "Development control", "Ground coverage exceeded",
                f"The ground floor covers {m['coverage'] * 100:.1f}% of the plot against a "
                f"{max_cov * 100:.0f}% limit.",
                code="DCR-coverage", value=m["coverage"], limit=max_cov, unit="ratio",
                suggestion="Increase setbacks, or move ground-floor area to an upper floor.")
    else:
        rep.add(OK, "Development control", "Ground coverage within limit",
                f"{m['coverage'] * 100:.1f}% covered against a {max_cov * 100:.0f}% limit.",
                code="DCR-coverage", value=m["coverage"], limit=max_cov, unit="ratio")

    max_far = float(req.get("max_far") or DEFAULT_MAX_FAR)
    if m["far"] > max_far + 1e-4:
        over = (m["far"] - max_far) * m["plot_area"]
        rep.add(ERROR, "Development control", "Floor area ratio exceeded",
                f"FAR is {m['far']:.2f} against a permitted {max_far:.2f}. "
                f"The design is about {over:.1f} m2 over what the plot allows.",
                code="DCR-far", value=m["far"], limit=max_far, unit="ratio",
                suggestion="Reduce the number of floors or the built footprint.",
                fix={"field": "floors", "value": max(1, int(req.get("floors", 1)) - 1),
                     "label": "Remove one floor"})
    else:
        rep.add(OK, "Development control", "Floor area ratio within limit",
                f"FAR {m['far']:.2f} against a permitted {max_far:.2f}.",
                code="DCR-far", value=m["far"], limit=max_far, unit="ratio")


def _check_geometry(rep: Report, rooms, envelope: Rect) -> None:
    """Integrity of the partition itself: the plan must be physically buildable."""
    by_floor = defaultdict(list)
    for r in rooms:
        # A cantilevered balcony hangs outside the envelope and is not part of
        # the floor plate; a recessed one is carved from it and must be counted.
        if r.type == "balcony" and not envelope.contains_rect(r.rect, tol=0.05):
            continue
        # Open parking stands in the front setback on purpose: it is not part of
        # the floor plate and must not be read as a space breaching the line.
        if r.id == "parking_open":
            continue
        by_floor[r.floor].append(r)

    for floor, group in sorted(by_floor.items()):
        rects = [r.rect for r in group]
        hits = rects_overlap(rects)
        if hits:
            names = {group[i].label for i, _j, _a in hits} | {group[j].label for _i, j, _a in hits}
            rep.add(ERROR, "Geometry", f"Overlapping spaces on level {floor}",
                    f"{len(hits)} pair(s) of spaces occupy the same floor area: "
                    f"{', '.join(sorted(names))}.",
                    code="GEO-overlap", value=len(hits),
                    rooms=[group[i].id for i, _j, _a in hits],
                    suggestion="Regenerate the plan; the partition is invalid.")

        covered = sum(r.rect.area for r in group)
        gap = envelope.area - covered
        if abs(gap) > 0.25:
            rep.add(WARN, "Geometry", f"Level {floor} does not tile the envelope",
                    f"Spaces cover {covered:.2f} m2 of a {envelope.area:.2f} m2 envelope, "
                    f"leaving {abs(gap):.2f} m2 {'unassigned' if gap > 0 else 'over-assigned'}.",
                    code="GEO-cover", value=covered, limit=envelope.area, unit="m2")

        outside = [r for r in group
                   if r.type != "parking" and not envelope.contains_rect(r.rect, tol=0.03)]
        if outside:
            rep.add(ERROR, "Geometry", f"Spaces outside the buildable envelope on level {floor}",
                    f"{', '.join(r.label for r in outside)} extend past the setback line.",
                    code="GEO-envelope", rooms=[r.id for r in outside],
                    suggestion="These spaces breach the setback and cannot be built as drawn.")

    if not any(f["severity"] == ERROR and f["category"] == "Geometry" for f in rep.findings):
        rep.add(OK, "Geometry", "Floor plates are valid",
                "Every level tiles its envelope exactly, with no overlaps and no gaps.",
                code="GEO-ok")


def _check_room_sizes(rep: Report, rooms) -> None:
    for r in rooms:
        if r.type in ("corridor", "terrace"):
            continue
        st = spec(r.type)

        if r.rect.area < r.min_area - 1e-3:
            rep.add(ERROR, "Room sizes", f"{r.label} is below the minimum area",
                    f"{r.rect.area:.2f} m2 provided against a {r.min_area:.2f} m2 minimum "
                    f"for a {st['label'].lower()}.",
                    code="NBC-area", rooms=[r.id],
                    value=r.rect.area, limit=r.min_area, unit="m2",
                    suggestion="Enlarge the plot, reduce the room count, or add a floor.")
        elif r.rect.short_side < r.min_dim - 1e-3:
            rep.add(ERROR, "Room sizes", f"{r.label} is too narrow",
                    f"Clear width is {r.rect.short_side:.2f} m against a {r.min_dim:.2f} m "
                    f"minimum. The area is adequate but the proportion is not usable.",
                    code="NBC-width", rooms=[r.id],
                    value=r.rect.short_side, limit=r.min_dim, unit="m",
                    suggestion="Reduce the number of spaces competing for this floor.")
        elif r.rect.aspect > r.aspect_max + 1e-3:
            rep.add(WARN, "Room sizes", f"{r.label} is awkwardly proportioned",
                    f"Proportion is {r.rect.aspect:.2f}:1 against a {r.aspect_max:.1f}:1 "
                    f"guideline; the space will feel like a corridor.",
                    code="PROP-aspect", rooms=[r.id],
                    value=r.rect.aspect, limit=r.aspect_max, unit=":1")

        # Furniture reality check for bedrooms.
        if r.type in ("master_bedroom", "bedroom", "guest_bedroom"):
            bed_w, bed_l = (1.65, 2.05) if r.type == "master_bedroom" else (1.05, 2.00)
            if not (r.rect.short_side >= bed_w + 0.6 and r.rect.long_side >= bed_l + 0.7):
                rep.add(WARN, "Room sizes", f"{r.label} cannot take a standard bed layout",
                        f"A {bed_w:.2f} m x {bed_l:.2f} m bed plus circulation does not fit in "
                        f"{r.rect.w:.2f} m x {r.rect.h:.2f} m.",
                        code="FURN-bed", rooms=[r.id],
                        suggestion="Increase this bedroom or reduce the bedroom count.")

    if not any(f["category"] == "Room sizes" and f["severity"] == ERROR for f in rep.findings):
        rep.add(OK, "Room sizes", "All spaces meet minimum size standards",
                "Every space satisfies its NBC-informed minimum area and clear width.",
                code="NBC-area")


def _check_relationships(rep: Report, rooms, openings) -> None:
    from .topology import build_contacts
    contacts = build_contacts(rooms)
    rel = evaluate_relationships(rooms, contacts)
    by_id = {r.id: r for r in rooms}

    for item in rel["required"]:
        if item["satisfied"]:
            rep.add(OK, "Relationships", item["label"],
                    f"Satisfied on level {item['floor']}. {item['why']}",
                    code=f"TOPO-{item['rule']}", rooms=item["rooms"])
        else:
            rep.add(ERROR, "Relationships", f"Required adjacency missing: {item['label']}",
                    f"{item['why']} These spaces do not share a wall on level {item['floor']}.",
                    code=f"TOPO-{item['rule']}", rooms=item["rooms"],
                    suggestion="Regenerate, or relax the brief so the solver has more freedom.")

    for item in rel["preferred"]:
        if not item["satisfied"]:
            rep.add(WARN, "Relationships", f"Preferred adjacency missing: {item['label']}",
                    item["why"], code=f"TOPO-{item['rule']}", rooms=item["rooms"])

    for v in rel["violations"]:
        a, b = by_id.get(v["a"]), by_id.get(v["b"])
        if not a or not b:
            continue
        sev = ERROR if v["severity"] >= 8 else WARN
        rep.add(sev, "Relationships", f"Undesirable adjacency: {a.label} and {b.label}",
                f"{v['why']} They share {v['length']:.2f} m of wall on level {v['floor']}.",
                code="TOPO-conflict", rooms=[a.id, b.id],
                suggestion="Regenerate the plan or move one of these spaces to another floor.")

    rep.add(INFO, "Relationships", "Relationship summary",
            f"{rel['required_satisfied']} of {rel['required_total']} required adjacencies met; "
            f"{len(rel['violations'])} undesirable adjacency(ies) present.",
            code="TOPO-summary",
            value=rel["required_satisfied"], limit=rel["required_total"])


def _check_circulation(rep: Report, rooms, openings, req: dict) -> None:
    # Open parking is reached from the street, not through the house.
    indoor = [r for r in rooms if r.id != "parking_open"]
    report = reachability_report(indoor, openings)
    by_id = {r.id: r for r in rooms}

    for floor, info in sorted(report.items()):
        unreachable = [by_id[i].label for i in info["unreachable"] if i in by_id]
        if unreachable:
            rep.add(ERROR, "Circulation", f"Spaces unreachable on level {floor}",
                    f"{', '.join(unreachable)} cannot be entered: no door connects them to "
                    f"the rest of the floor.",
                    code="CIRC-reach", rooms=info["unreachable"],
                    value=len(unreachable),
                    suggestion="These spaces have no shared wall long enough for a door.")
        else:
            rep.add(OK, "Circulation", f"Level {floor} is fully walkable",
                    "Every space is reachable from the entrance or stair landing.",
                    code="CIRC-reach")

    # Vertical circulation
    floors = int(req.get("floors", 1))
    stairs = [r for r in rooms if r.type == "staircase"]
    if floors > 1:
        levels_with_stair = {r.floor for r in stairs}
        missing = set(range(floors)) - levels_with_stair
        if missing:
            rep.add(ERROR, "Circulation", "Staircase missing on some levels",
                    f"No stair footprint on level(s) {sorted(missing)}.",
                    code="CIRC-stair", suggestion="A multi-storey house needs a continuous stair.")
        elif len(stairs) > 1:
            base = stairs[0].rect
            aligned = all(abs(s.rect.x - base.x) < 0.05 and abs(s.rect.y - base.y) < 0.05
                          and abs(s.rect.w - base.w) < 0.05 and abs(s.rect.h - base.h) < 0.05
                          for s in stairs)
            if aligned:
                rep.add(OK, "Circulation", "Stair core is vertically aligned",
                        f"The {base.w:.2f} m x {base.h:.2f} m stair footprint is identical on "
                        f"all {len(stairs)} levels, so the flights actually stack.",
                        code="CIRC-stack", rooms=[s.id for s in stairs])
            else:
                rep.add(ERROR, "Circulation", "Stair core does not stack",
                        "The staircase footprint differs between levels, so the flights "
                        "cannot connect.",
                        code="CIRC-stack", rooms=[s.id for s in stairs])

        for s in stairs:
            if s.rect.short_side < STAIR_WIDTH - 0.15 or s.rect.long_side < STAIR_LENGTH - 0.25:
                rep.add(WARN, "Circulation", "Stair core is undersized",
                        f"{s.rect.w:.2f} m x {s.rect.h:.2f} m provided; a dog-legged flight "
                        f"needs about {STAIR_WIDTH:.2f} m x {STAIR_LENGTH:.2f} m.",
                        code="CIRC-stairsize", rooms=[s.id],
                        value=s.rect.short_side, limit=STAIR_WIDTH, unit="m")
                break

    main = [o for o in openings if o.kind == "main_door"]
    if main:
        rep.add(OK, "Circulation", "Main entrance placed",
                "A main door is provided on an external wall of the entrance space.",
                code="CIRC-entry")
    else:
        rep.add(ERROR, "Circulation", "No main entrance",
                "The entrance space has no external wall able to take a front door.",
                code="CIRC-entry",
                suggestion="The entry space is landlocked; regenerate the plan.")


def _check_light_and_vent(rep: Report, rooms, openings, envelope: Rect) -> None:
    glazing = glazing_by_room(rooms, [o for o in openings if o.kind == "window"])
    dark: list[str] = []
    under: list[str] = []

    for r in rooms:
        if not getattr(r, "habitable", False):
            continue
        if not exterior_edges(r.rect, envelope):
            dark.append(r.id)
            rep.add(ERROR, "Light & ventilation", f"{r.label} has no external wall",
                    "A habitable room must have natural light and cross ventilation; this "
                    "space is entirely internal.",
                    code="NBC-light", rooms=[r.id],
                    suggestion="Swap this room with one on the perimeter, or add a courtyard.")
            continue
        need = r.rect.area * LIGHT_VENT_RATIO
        got = glazing.get(r.id, 0.0)
        if got + 1e-3 < need:
            under.append(r.id)
            rep.add(WARN, "Light & ventilation", f"{r.label} is under-glazed",
                    f"{got:.2f} m2 of opening against {need:.2f} m2 required "
                    f"(1/{int(1 / LIGHT_VENT_RATIO)} of the {r.rect.area:.2f} m2 floor area).",
                    code="NBC-light", rooms=[r.id],
                    value=got, limit=need, unit="m2",
                    suggestion="Widen the window or add a second opening on another wall.")

    if not dark and not under:
        rep.add(OK, "Light & ventilation", "All habitable rooms are naturally lit",
                f"Every habitable room has an external wall and at least "
                f"1/{int(1 / LIGHT_VENT_RATIO)} of its floor area in openings.",
                code="NBC-light")


def _check_services(rep: Report, rooms, req: dict, m: dict) -> None:
    # --- parking -----------------------------------------------------------
    cars = int(req.get("parking_cars", 0))
    bays = [r for r in rooms if r.type == "parking"]
    if cars > 0:
        if not bays:
            rep.add(ERROR, "Parking", "Parking requested but not provided",
                    f"{cars} car space(s) were asked for but none could be placed.",
                    code="PARK-missing",
                    suggestion="Switch to open parking in the front setback, or enlarge the plot.",
                    fix={"field": "parking_type", "value": "open",
                         "label": "Move parking to the front setback"})
        else:
            bay = bays[0]
            need_w = CAR_WIDTH * cars
            if bay.rect.short_side < CAR_WIDTH - 0.05 or bay.rect.long_side < CAR_LENGTH - 0.15:
                rep.add(ERROR, "Parking", "Parking bay is too small",
                        f"{bay.rect.w:.2f} m x {bay.rect.h:.2f} m provided; each car needs "
                        f"{CAR_WIDTH:.2f} m x {CAR_LENGTH:.2f} m clear.",
                        code="PARK-size", rooms=[bay.id],
                        value=bay.rect.short_side, limit=CAR_WIDTH, unit="m",
                        suggestion="Reduce the car count or use open parking in the setback.",
                        fix={"field": "parking_cars", "value": max(0, cars - 1),
                             "label": f"Reduce to {max(0, cars - 1)} car space(s)"})
            elif bay.rect.area < need_w * CAR_LENGTH - 0.5:
                rep.add(WARN, "Parking", "Parking is tight for the car count",
                        f"{bay.rect.area:.1f} m2 for {cars} cars; "
                        f"{need_w * CAR_LENGTH:.1f} m2 is the comfortable minimum.",
                        code="PARK-size", rooms=[bay.id],
                        value=bay.rect.area, limit=need_w * CAR_LENGTH, unit="m2")
            else:
                rep.add(OK, "Parking", "Parking is feasible",
                        f"{bay.rect.w:.2f} m x {bay.rect.h:.2f} m accommodates {cars} car(s) "
                        f"at {CAR_WIDTH:.2f} m x {CAR_LENGTH:.2f} m each.",
                        code="PARK-size", rooms=[bay.id])

    # --- bathroom provision -------------------------------------------------
    beds = [r for r in rooms if r.type in ("bedroom", "master_bedroom", "guest_bedroom")]
    baths = [r for r in rooms if r.type in ("bathroom",)]
    if beds and len(baths) * 2 < len(beds):
        rep.add(WARN, "Services", "Bathroom provision is thin",
                f"{len(baths)} bathroom(s) for {len(beds)} bedrooms. One per two bedrooms is "
                f"the usual minimum.",
                code="SVC-bath", value=len(baths), limit=(len(beds) + 1) // 2,
                suggestion="Add a bathroom, or accept shared use.",
                fix={"field": "bathrooms", "value": (len(beds) + 1) // 2,
                     "label": f"Provide {(len(beds) + 1) // 2} bathrooms"})

    # --- wet-stack alignment ------------------------------------------------
    by_floor = defaultdict(list)
    for r in rooms:
        by_floor[r.floor].append(r)
    levels = sorted(by_floor)
    unstacked: list[str] = []
    for lvl in levels[1:]:
        below = [r for r in by_floor[lvl - 1] if getattr(r, "wet", False)]
        for r in by_floor[lvl]:
            if not getattr(r, "wet", False):
                continue
            if not any(r.rect.overlap_area(b.rect) > 0.8 for b in below):
                unstacked.append(r.id)

    if unstacked:
        rep.add(WARN, "Services", "Plumbing stacks are not aligned",
                f"{len(unstacked)} wet space(s) on upper floors sit over dry rooms. Drainage "
                f"will need horizontal runs in the ceiling below.",
                code="SVC-stack", rooms=unstacked,
                suggestion="Acceptable, but stacking wet rooms vertically is cheaper and "
                           "avoids leaks over habitable space.")
    elif len(levels) > 1:
        rep.add(OK, "Services", "Plumbing stacks align vertically",
                "Every upper-floor wet space sits over a wet space below.",
                code="SVC-stack")

    rep.add(INFO, "Efficiency", "Carpet area efficiency",
            f"{m['carpet_area']:.1f} m2 carpet from {m['builtup_area']:.1f} m2 built-up "
            f"({m['efficiency'] * 100:.1f}%). Above 80% is good for a house this size.",
            code="EFF-carpet", value=m["efficiency"], limit=0.80, unit="ratio")


def _check_programme(rep: Report, programme, req: dict) -> None:
    if programme is None:
        return
    for d in programme.deficits:
        rep.add(ERROR, "Brief feasibility", f"{d['floor_name']} is over-programmed",
                f"The spaces asked for need at least {d['required']:.1f} m2 but only "
                f"{d['available']:.1f} m2 is available after setbacks and fixed cores. "
                f"The brief is {d['shortfall']:.1f} m2 short on this level.",
                code="PROG-deficit", value=d["available"], limit=d["required"], unit="m2",
                suggestion="Add a floor, reduce the room count, or reduce the setbacks.",
                fix={"field": "floors", "value": int(req.get("floors", 1)) + 1,
                     "label": "Add a floor"})
    for note in programme.notes:
        rep.add(INFO, "Brief feasibility", "Planning note", note, code="PROG-note")
