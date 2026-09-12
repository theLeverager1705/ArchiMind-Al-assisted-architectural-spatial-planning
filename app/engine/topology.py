"""
Topological post-processing of a placed layout.

Once every space has a rectangle, this module derives the things that make a
drawing an actual plan rather than a diagram of boxes:

  * which spaces touch, and along how much wall
  * where doors go (required relationships first, then whatever else is needed
    to make every space reachable from the entrance)
  * where windows go, sized from the NBC light-and-ventilation ratio
  * the merged wall network, which the 3D view extrudes directly

Everything here works on duck-typed rooms exposing .id, .type, .floor, .rect.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from .geometry import Edge, Rect, exterior_edges, shared_edge
from .standards import (
    ADJACENCY_RULES, DOOR_WIDTH, DOOR_WIDTH_MAIN, DOOR_WIDTH_SMALL,
    LIGHT_VENT_RATIO, MIN_OPENING_WALL, WINDOW_HEIGHT, adjacency_weight, spec,
)

# Spaces that are open-sided and therefore never get windows or a solid wall run.
OPEN_SPACES = {"balcony", "terrace", "parking"}
# Narrow doors
SMALL_DOOR_SPACES = {"bathroom", "toilet", "store", "utility", "pooja"}


@dataclass
class Contact:
    """Two spaces sharing a wall."""
    a: str
    b: str
    type_a: str
    type_b: str
    floor: int
    edge: Edge
    length: float
    weight: float
    required: bool
    why: str

    def as_dict(self) -> dict:
        return {
            "a": self.a, "b": self.b, "floor": self.floor,
            "length": round(self.length, 2), "weight": self.weight,
            "required": self.required, "why": self.why,
            "edge": self.edge.as_dict(),
        }


@dataclass
class Opening:
    """A door or window cut into a wall."""
    id: str
    kind: str            # door | main_door | window | opening
    floor: int
    x: float             # centre point
    y: float
    orientation: str     # h | v  (the wall it sits in)
    width: float
    rooms: list[str] = field(default_factory=list)
    label: str = ""
    swing: int = 1       # +1 / -1, which side the leaf opens towards

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "floor": self.floor,
            "x": round(self.x, 3), "y": round(self.y, 3),
            "orientation": self.orientation, "width": round(self.width, 3),
            "rooms": self.rooms, "label": self.label, "swing": self.swing,
        }


@dataclass
class Wall:
    floor: int
    x1: float
    y1: float
    x2: float
    y2: float
    orientation: str
    exterior: bool

    @property
    def length(self) -> float:
        return abs(self.x2 - self.x1) + abs(self.y2 - self.y1)

    def as_dict(self) -> dict:
        return {
            "floor": self.floor, "x1": round(self.x1, 3), "y1": round(self.y1, 3),
            "x2": round(self.x2, 3), "y2": round(self.y2, 3),
            "orientation": self.orientation, "exterior": self.exterior,
        }


# --------------------------------------------------------------------------
# Adjacency
# --------------------------------------------------------------------------
def build_contacts(rooms: list) -> list[Contact]:
    """Every pair of same-floor rooms that share a usable length of wall."""
    contacts: list[Contact] = []
    by_floor: dict[int, list] = defaultdict(list)
    for r in rooms:
        by_floor[r.floor].append(r)

    for floor, group in by_floor.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                edge = shared_edge(a.rect, b.rect)
                if edge is None or edge.length < 0.25:
                    continue
                w, required, why = adjacency_weight(a.type, b.type)
                contacts.append(Contact(
                    a=a.id, b=b.id, type_a=a.type, type_b=b.type, floor=floor,
                    edge=edge, length=edge.length, weight=w, required=required, why=why,
                ))
    return contacts


def contact_lookup(contacts: list[Contact]) -> dict[tuple[str, str], Contact]:
    out: dict[tuple[str, str], Contact] = {}
    for c in contacts:
        out[(c.a, c.b)] = c
        out[(c.b, c.a)] = c
    return out


# Relationships checked once per instance rather than once per floor, because
# every bedroom needs its own bathroom nearby, not just one bedroom on the floor.
PER_INSTANCE_RULES = {("bedroom", "bathroom"), ("guest_bedroom", "bathroom")}


def evaluate_relationships(rooms: list, contacts: list[Contact]) -> dict:
    """
    Check the placed layout against the topological rules.

    One implementation feeds two consumers: the layout scorer (which uses the
    aggregate ratios to rank candidates) and the validator (which turns the
    individual failures into user-facing findings). Keeping them on the same code
    path means the score the user sees always matches the issues listed.
    """
    by_floor: dict[int, list] = defaultdict(list)
    for r in rooms:
        by_floor[r.floor].append(r)

    adjacent: set[tuple[str, str]] = set()
    for c in contacts:
        adjacent.add((c.a, c.b))
        adjacent.add((c.b, c.a))

    required: list[dict] = []
    preferred: list[dict] = []
    violations: list[dict] = []

    def of_type(group: list, t: str) -> list:
        return [r for r in group if r.type == t]

    for rule in ADJACENCY_RULES:
        if rule["weight"] <= 0:
            continue
        ta, tb = rule["a"], rule["b"]
        bucket = required if rule["required"] else preferred

        for floor in sorted(by_floor):
            group = by_floor[floor]
            A, B = of_type(group, ta), of_type(group, tb)
            if not A or not B:
                continue

            # An en-suite is checked against its own bedroom, not any bathroom.
            if ta == "master_bedroom" and tb == "bathroom":
                for master in A:
                    ensuite = next((r for r in B if r.attached_to == master.id), None)
                    partners = [ensuite] if ensuite else B
                    ok = any((master.id, p.id) in adjacent for p in partners if p)
                    bucket.append({
                        "rule": f"{ta}-{tb}", "floor": floor, "satisfied": ok,
                        "weight": rule["weight"], "why": rule["why"],
                        "rooms": [master.id] + [p.id for p in partners if p],
                        "label": f"{master.label} needs its attached bathroom alongside it",
                    })
                continue

            if (ta, tb) in PER_INSTANCE_RULES or (tb, ta) in PER_INSTANCE_RULES:
                multi, other = (A, B) if (ta, tb) in PER_INSTANCE_RULES else (B, A)
                for m in multi:
                    ok = any((m.id, o.id) in adjacent for o in other)
                    bucket.append({
                        "rule": f"{ta}-{tb}", "floor": floor, "satisfied": ok,
                        "weight": rule["weight"], "why": rule["why"],
                        "rooms": [m.id],
                        "label": f"{m.label} should adjoin a bathroom",
                    })
                continue

            ok = any((a.id, b.id) in adjacent for a in A for b in B)
            bucket.append({
                "rule": f"{ta}-{tb}", "floor": floor, "satisfied": ok,
                "weight": rule["weight"], "why": rule["why"],
                "rooms": [A[0].id, B[0].id],
                "label": f"{spec(ta)['label']} to {spec(tb)['label']}",
            })

    # Negative relationships that the layout nevertheless created.
    for c in contacts:
        if c.weight < 0:
            violations.append({
                "a": c.a, "b": c.b, "floor": c.floor,
                "types": [c.type_a, c.type_b], "why": c.why,
                "severity": abs(c.weight), "length": round(c.length, 2),
            })

    req_total = len(required)
    req_ok = sum(1 for r in required if r["satisfied"])
    pref_weight = sum(p["weight"] for p in preferred)
    pref_ok = sum(p["weight"] for p in preferred if p["satisfied"])

    return {
        "required": required,
        "preferred": preferred,
        "violations": violations,
        "required_score": (req_ok / req_total) if req_total else 1.0,
        "preferred_score": (pref_ok / pref_weight) if pref_weight else 1.0,
        "required_satisfied": req_ok,
        "required_total": req_total,
        "violation_count": len(violations),
    }


# --------------------------------------------------------------------------
# Doors
# --------------------------------------------------------------------------
def _door_width(type_a: str, type_b: str) -> float:
    if type_a in SMALL_DOOR_SPACES or type_b in SMALL_DOOR_SPACES:
        return DOOR_WIDTH_SMALL
    return DOOR_WIDTH


def _opening_on_edge(edge: Edge, width: float) -> tuple[float, float, float] | None:
    """
    Centre an opening of the given width on a wall segment, keeping a jamb
    margin at both ends. Returns (cx, cy, width) or None if it will not fit.
    """
    margin = 0.12
    usable = edge.length - 2 * margin
    if usable < 0.6:
        return None
    w = min(width, usable)
    cx, cy = edge.mid
    return cx, cy, w


def place_doors(rooms: list, contacts: list[Contact], envelope: Rect) -> list[Opening]:
    """
    Door strategy, in priority order:

      1. every required relationship that has a shared wall gets a door
      2. strongly preferred relationships get a door where one fits
      3. any space still unreachable from the entrance gets connected through
         its best remaining contact (a spanning tree over the contact graph)

    Step 3 is what guarantees a walkable plan; step 1 and 2 are what make the
    circulation sensible rather than merely connected.
    """
    rooms_by_id = {r.id: r for r in rooms}
    openings: list[Opening] = []
    used: set[tuple[str, str]] = set()
    counter = 0

    def key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def add_door(c: Contact, kind: str = "door") -> bool:
        nonlocal counter
        k = key(c.a, c.b)
        if k in used:
            return False
        ta, tb = c.type_a, c.type_b
        if ta in OPEN_SPACES and tb in OPEN_SPACES:
            return False
        if c.length < MIN_OPENING_WALL:
            return False
        placed = _opening_on_edge(c.edge, _door_width(ta, tb))
        if placed is None:
            return False
        cx, cy, w = placed
        counter += 1
        used.add(k)
        ra, rb = rooms_by_id[c.a], rooms_by_id[c.b]
        # Swing towards the larger room, which is how doors are normally hung.
        swing = 1 if ra.rect.area >= rb.rect.area else -1
        openings.append(Opening(
            id=f"d{counter}", kind=kind, floor=c.floor, x=cx, y=cy,
            orientation=c.edge.orientation, width=w, rooms=[c.a, c.b],
            label=f"{ra.label} - {rb.label}", swing=swing,
        ))
        return True

    ordered = sorted(contacts, key=lambda c: (-int(c.required), -c.weight, -c.length))

    # 1 + 2: relationship-driven doors
    for c in ordered:
        if c.weight <= 0:
            continue
        if c.required or c.weight >= 5:
            add_door(c)

    # --- main entrance door -------------------------------------------------
    entry = _entrance_room(rooms, envelope)
    if entry is not None:
        ext = exterior_edges(entry.rect, envelope)
        # Rank walls by how sensible a front door on them would be: the street
        # frontage first, then the sides, and the rear wall only as a last
        # resort. Without the explicit rear penalty the longest wall wins and
        # the house ends up entered from the back garden.
        def _rank(e):
            if e.orientation == "h" and abs(e.y1 - envelope.y) < 0.03:
                return 0                                   # street frontage
            if e.orientation == "v":
                return 1                                   # side wall
            return 2                                       # rear wall
        ext.sort(key=lambda e: (_rank(e), -e.length))
        if ext:
            placed = _opening_on_edge(ext[0], DOOR_WIDTH_MAIN)
            if placed:
                cx, cy, w = placed
                counter += 1
                openings.append(Opening(
                    id=f"d{counter}", kind="main_door", floor=entry.floor, x=cx, y=cy,
                    orientation=ext[0].orientation, width=w, rooms=[entry.id],
                    label="Main Entrance", swing=1,
                ))

    # 3: connectivity repair, per floor
    for floor in sorted({r.floor for r in rooms}):
        floor_rooms = [r for r in rooms if r.floor == floor]
        floor_contacts = [c for c in contacts if c.floor == floor]
        root = _floor_root(floor_rooms)
        if root is None:
            continue

        for _ in range(len(floor_rooms) + 2):
            reachable = _reachable(floor_rooms, openings, root.id)
            missing = [r for r in floor_rooms if r.id not in reachable]
            if not missing:
                break
            # Connect the unreachable room that has the best available contact.
            best: tuple[float, Contact] | None = None
            for c in floor_contacts:
                in_a, in_b = c.a in reachable, c.b in reachable
                if in_a == in_b:
                    continue  # both inside or both outside: not a frontier edge
                if key(c.a, c.b) in used:
                    continue
                if c.weight < 0:
                    continue  # never cut a door through a forbidden adjacency
                score = c.weight * 2 + c.length
                if best is None or score > best[0]:
                    best = (score, c)
            if best is None:
                break
            if not add_door(best[1], kind="opening"):
                # Could not physically fit a door here; drop this contact and retry.
                used.add(key(best[1].a, best[1].b))

    return openings


def _entrance_room(rooms: list, envelope: Rect | None = None):
    """
    Where the front door goes: the foyer normally, but only if it can actually
    reach an external wall. A landlocked foyer means the main door has to be hung
    off the next-best public room instead of being dropped silently.
    """
    candidates = [r for r in rooms
                  if r.floor == 0 and r.type in ("foyer", "living", "dining")]
    if envelope is not None:
        order = {"foyer": 0, "living": 1, "dining": 2}

        def _key(r):
            edges = exterior_edges(r.rect, envelope)
            has_front = any(e.orientation == "h" and abs(e.y1 - envelope.y) < 0.03
                            and e.length >= 0.9 for e in edges)
            has_side = any(e.orientation == "v" and e.length >= 0.9 for e in edges)
            access = 0 if has_front else (1 if has_side else 2)
            return (access, order.get(r.type, 3))

        reachable = [r for r in candidates if exterior_edges(r.rect, envelope)]
        if reachable:
            reachable.sort(key=_key)
            return reachable[0]
    if candidates:
        return candidates[0]
    ground = [r for r in rooms if r.floor == 0 and r.type not in OPEN_SPACES]
    return ground[0] if ground else None


def _floor_root(floor_rooms: list):
    """Where circulation starts on a floor: the foyer, else the stair, else living."""
    for t in ("foyer", "staircase", "living", "dining"):
        for r in floor_rooms:
            if r.type == t:
                return r
    return floor_rooms[0] if floor_rooms else None


def _reachable(floor_rooms: list, openings: list[Opening], root_id: str) -> set[str]:
    ids = {r.id for r in floor_rooms}
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for o in openings:
        if len(o.rooms) == 2 and o.rooms[0] in ids and o.rooms[1] in ids:
            adj[o.rooms[0]].add(o.rooms[1])
            adj[o.rooms[1]].add(o.rooms[0])

    seen = {root_id}
    q = deque([root_id])
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def reachability_report(rooms: list, openings: list[Opening]) -> dict[int, dict]:
    """Per-floor reachability, used by both the scorer and the validator."""
    out: dict[int, dict] = {}
    for floor in sorted({r.floor for r in rooms}):
        floor_rooms = [r for r in rooms if r.floor == floor]
        root = _floor_root(floor_rooms)
        if root is None:
            continue
        seen = _reachable(floor_rooms, openings, root.id)
        unreachable = [r.id for r in floor_rooms if r.id not in seen]
        out[floor] = {
            "root": root.id,
            "reachable": sorted(seen),
            "unreachable": unreachable,
            "ratio": len(seen) / max(1, len(floor_rooms)),
        }
    return out


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
def place_windows(rooms: list, envelope: Rect, doors: list[Opening]) -> list[Opening]:
    """
    Size glazing from the NBC light-and-ventilation rule: a habitable room needs
    openings of at least one tenth of its floor area. Windows are spread over the
    room's available external walls, avoiding the door positions.
    """
    out: list[Opening] = []
    counter = 0
    door_spots: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    for d in doors:
        door_spots[d.floor].append((d.x, d.y, d.width))

    for r in rooms:
        if r.type in OPEN_SPACES:
            continue
        edges = exterior_edges(r.rect, envelope)
        if not edges:
            continue

        st = spec(r.type)
        if st["habitable"]:
            need_area = r.rect.area * LIGHT_VENT_RATIO
        elif r.type in ("bathroom", "toilet", "utility", "staircase"):
            need_area = 0.55          # a ventilator is enough
        else:
            need_area = 0.0
        if need_area <= 0:
            continue

        need_width = need_area / WINDOW_HEIGHT
        edges.sort(key=lambda e: -e.length)

        for e in edges:
            if need_width <= 0.05:
                break
            usable = e.length - 0.7
            if usable < 0.6:
                continue
            w = min(need_width, usable, 2.40)
            cx, cy = e.mid
            # Slide off any door sitting on the same wall line.
            for dx, dy, dw in door_spots[r.floor]:
                clear = (w + dw) / 2 + 0.15
                if e.orientation == "v" and abs(dx - cx) < 0.06 and abs(dy - cy) < clear:
                    cy = dy + clear
                elif e.orientation == "h" and abs(dy - cy) < 0.06 and abs(dx - cx) < clear:
                    cx = dx + clear
            # Keep the window inside its wall.
            if e.orientation == "v":
                lo, hi = min(e.y1, e.y2) + w / 2 + 0.25, max(e.y1, e.y2) - w / 2 - 0.25
                cy = min(max(cy, lo), hi) if hi >= lo else (e.y1 + e.y2) / 2
            else:
                lo, hi = min(e.x1, e.x2) + w / 2 + 0.25, max(e.x1, e.x2) - w / 2 - 0.25
                cx = min(max(cx, lo), hi) if hi >= lo else (e.x1 + e.x2) / 2

            counter += 1
            out.append(Opening(
                id=f"w{counter}", kind="window", floor=r.floor, x=cx, y=cy,
                orientation=e.orientation, width=round(w, 3), rooms=[r.id],
                label=f"{r.label} window",
            ))
            need_width -= w

    return out


def glazing_by_room(rooms: list, windows: list[Opening]) -> dict[str, float]:
    """Total glazed area per room id, for the light-and-ventilation check."""
    out: dict[str, float] = defaultdict(float)
    for w in windows:
        if w.rooms:
            out[w.rooms[0]] += w.width * WINDOW_HEIGHT
    return dict(out)


# --------------------------------------------------------------------------
# Wall network
# --------------------------------------------------------------------------
def _merge_intervals(ivs: list[tuple[float, float]], tol: float = 1e-3) -> list[tuple[float, float]]:
    if not ivs:
        return []
    ivs = sorted(ivs)
    merged = [list(ivs[0])]
    for lo, hi in ivs[1:]:
        if lo <= merged[-1][1] + tol:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(a, b) for a, b in merged]


def extract_walls(rooms: list, envelope: Rect, tol: float = 0.02) -> list[Wall]:
    """
    Collapse every room boundary into a merged, non-duplicated wall network.

    Rooms share boundaries, so naively extruding four walls per room would give
    doubled geometry in 3D. Collecting edges per grid line and merging the
    intervals produces exactly one wall run per physical wall.
    """
    walls: list[Wall] = []
    for floor in sorted({r.floor for r in rooms}):
        vert: dict[float, list[tuple[float, float]]] = defaultdict(list)
        horiz: dict[float, list[tuple[float, float]]] = defaultdict(list)

        for r in rooms:
            if r.floor != floor or r.type in ("balcony", "terrace"):
                continue
            rc = r.rect
            vert[round(rc.x, 2)].append((rc.y, rc.y2))
            vert[round(rc.x2, 2)].append((rc.y, rc.y2))
            horiz[round(rc.y, 2)].append((rc.x, rc.x2))
            horiz[round(rc.y2, 2)].append((rc.x, rc.x2))

        for x, ivs in vert.items():
            ext = abs(x - envelope.x) <= tol or abs(x - envelope.x2) <= tol
            for lo, hi in _merge_intervals(ivs):
                walls.append(Wall(floor, x, lo, x, hi, "v", ext))
        for y, ivs in horiz.items():
            ext = abs(y - envelope.y) <= tol or abs(y - envelope.y2) <= tol
            for lo, hi in _merge_intervals(ivs):
                walls.append(Wall(floor, lo, y, hi, y, "h", ext))

    return walls


def wall_face_area(walls: list[Wall], height: float) -> float:
    """Total plastered/painted wall face area, counting both faces. Cost driver."""
    return sum(w.length for w in walls) * height * 2.0
