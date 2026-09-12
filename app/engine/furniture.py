"""
Furniture and fixture layout.

A floor plan that shows only labelled rectangles is hard to judge. Drawing the
bed, the counter run and the sanitary fittings is also a real feasibility check:
if the standard furniture for a room will not fit with its clearances, the room
is too small whatever its area says.

Each item is emitted in world coordinates so the SVG renderer and the 3D view can
both consume the same list.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Rect

CLEARANCE = 0.70          # walking clearance kept in front of a door leaf


@dataclass
class Furniture:
    kind: str
    room: str
    x: float
    y: float
    w: float
    h: float
    rot: int = 0          # 0/90/180/270, used by the renderer for symbol direction

    def as_dict(self) -> dict:
        return {"kind": self.kind, "room": self.room,
                "x": round(self.x, 3), "y": round(self.y, 3),
                "w": round(self.w, 3), "h": round(self.h, 3), "rot": self.rot}

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)


# Which wall of a room an item is placed against.
N, S, E, W = "N", "S", "E", "W"


def _against(room: Rect, side: str, depth: float, width: float,
             offset: float = 0.0) -> Rect:
    """A rectangle of the given size placed against one wall of the room."""
    if side == S:
        w = min(width, room.w)
        return Rect(room.cx - w / 2 + offset, room.y, w, min(depth, room.h))
    if side == N:
        w = min(width, room.w)
        return Rect(room.cx - w / 2 + offset, room.y2 - min(depth, room.h), w, min(depth, room.h))
    if side == W:
        h = min(width, room.h)
        return Rect(room.x, room.cy - h / 2 + offset, min(depth, room.w), h)
    h = min(width, room.h)
    return Rect(room.x2 - min(depth, room.w), room.cy - h / 2 + offset, min(depth, room.w), h)


def _corner(room: Rect, corner: str, w: float, h: float) -> Rect:
    w, h = min(w, room.w), min(h, room.h)
    x = room.x if "W" in corner else room.x2 - w
    y = room.y if "S" in corner else room.y2 - h
    return Rect(x, y, w, h)


def _free(candidate: Rect, taken: list[Rect], blocked: list[Rect]) -> bool:
    if candidate.w <= 0.05 or candidate.h <= 0.05:
        return False
    for t in taken:
        if candidate.overlap_area(t) > 0.02:
            return False
    for b in blocked:
        if candidate.overlap_area(b) > 0.10:
            return False
    return True


def _door_blocks(room: Rect, doors: list) -> list[Rect]:
    """Clearance zones in front of every door opening onto this room."""
    out: list[Rect] = []
    for d in doors:
        if not room.contains_point(d.x, d.y, tol=0.35):
            continue
        if d.orientation == "v":
            out.append(Rect(d.x - CLEARANCE, d.y - d.width / 2, CLEARANCE * 2, d.width))
        else:
            out.append(Rect(d.x - d.width / 2, d.y - CLEARANCE, d.width, CLEARANCE * 2))
    return out


def _long_side(room: Rect) -> str:
    """The wall an occupant would naturally place the main furniture against."""
    return S if room.w >= room.h else W


def _sides_by_preference(room: Rect) -> list[str]:
    return [N, S, E, W] if room.w >= room.h else [W, E, N, S]


def furnish_room(room, doors: list) -> list[Furniture]:
    """Generate the fixtures for one placed room."""
    r = room.rect
    t = room.type
    blocked = _door_blocks(r, doors)
    taken: list[Rect] = []
    out: list[Furniture] = []

    def place(kind: str, sides: list[str], depth: float, width: float,
              rot_for: dict[str, int] | None = None, required: bool = False) -> bool:
        for side in sides:
            cand = _against(r, side, depth, width)
            if _free(cand, taken, blocked):
                taken.append(cand)
                rot = (rot_for or {}).get(side, 0)
                out.append(Furniture(kind, room.id, cand.x, cand.y, cand.w, cand.h, rot))
                return True
        if required:
            cand = _against(r, sides[0], depth, width)
            if cand.w > 0.05 and cand.h > 0.05:
                taken.append(cand)
                out.append(Furniture(kind, room.id, cand.x, cand.y, cand.w, cand.h,
                                     (rot_for or {}).get(sides[0], 0)))
                return True
        return False

    # ---- bedrooms ---------------------------------------------------------
    if t in ("master_bedroom", "bedroom", "guest_bedroom"):
        double = t == "master_bedroom" or r.area >= 11.0
        bed_w, bed_l = (1.65, 2.05) if double else (1.05, 2.00)
        rot_map = {S: 0, N: 180, W: 90, E: 270}
        for side in _sides_by_preference(r):
            depth, width = (bed_l, bed_w) if side in (N, S) else (bed_w, bed_l)
            cand = _against(r, side, depth, width)
            if _free(cand, taken, blocked) and cand.w >= 0.9 and cand.h >= 0.9:
                taken.append(cand)
                out.append(Furniture("bed_double" if double else "bed_single",
                                     room.id, cand.x, cand.y, cand.w, cand.h, rot_map[side]))
                break
        place("wardrobe", _sides_by_preference(r)[::-1], 0.60, min(2.0, max(r.w, r.h) * 0.5),
              {S: 0, N: 180, W: 90, E: 270})
        if r.area >= 13.0:
            place("desk", [E, W, N, S], 0.55, 1.10, {S: 0, N: 180, W: 90, E: 270})

    # ---- living -----------------------------------------------------------
    elif t == "living":
        place("sofa", _sides_by_preference(r), 0.88, min(2.30, max(r.w, r.h) * 0.7),
              {S: 0, N: 180, W: 90, E: 270}, required=True)
        place("tv_unit", _sides_by_preference(r)[::-1], 0.42, min(1.70, max(r.w, r.h) * 0.55),
              {S: 0, N: 180, W: 90, E: 270})
        ct = Rect(r.cx - 0.55, r.cy - 0.32, 1.10, 0.64)
        if _free(ct, taken, blocked):
            taken.append(ct)
            out.append(Furniture("coffee_table", room.id, ct.x, ct.y, ct.w, ct.h))

    # ---- dining -----------------------------------------------------------
    elif t == "dining":
        seats = 6 if r.area >= 11 else 4
        tw, th = (1.60, 0.90) if r.w >= r.h else (0.90, 1.60)
        tw, th = min(tw, r.w - 1.1), min(th, r.h - 1.1)
        if tw > 0.5 and th > 0.5:
            tbl = Rect(r.cx - tw / 2, r.cy - th / 2, tw, th)
            taken.append(tbl)
            out.append(Furniture("dining_table", room.id, tbl.x, tbl.y, tbl.w, tbl.h, seats))

    # ---- kitchen ----------------------------------------------------------
    elif t == "kitchen":
        # An L-shaped counter run along the two longest walls.
        d = 0.60
        if r.w >= r.h:
            run1 = Rect(r.x, r.y2 - d, r.w, d)
            run2 = Rect(r.x, r.y, d, max(0.0, r.h - d))
        else:
            run1 = Rect(r.x2 - d, r.y, d, r.h)
            run2 = Rect(r.x, r.y, max(0.0, r.w - d), d)
        for run in (run1, run2):
            if run.w > 0.3 and run.h > 0.3:
                taken.append(run)
                out.append(Furniture("counter", room.id, run.x, run.y, run.w, run.h))
        # Sink on the longer run, hob on the other.
        main = run1 if run1.area >= run2.area else run2
        other = run2 if main is run1 else run1
        if main.w > 0.8 or main.h > 0.8:
            if main.w >= main.h:
                out.append(Furniture("sink", room.id, main.x + main.w * 0.25 - 0.3,
                                     main.y + 0.05, 0.60, 0.50))
            else:
                out.append(Furniture("sink", room.id, main.x + 0.05,
                                     main.y + main.h * 0.25 - 0.3, 0.50, 0.60))
        if other.w > 0.7 or other.h > 0.7:
            if other.w >= other.h:
                out.append(Furniture("hob", room.id, other.x + other.w * 0.6 - 0.3,
                                     other.y + 0.06, 0.60, 0.48))
            else:
                out.append(Furniture("hob", room.id, other.x + 0.06,
                                     other.y + other.h * 0.6 - 0.3, 0.48, 0.60))
        place("fridge", [N, E, W, S], 0.65, 0.70)

    # ---- wet rooms --------------------------------------------------------
    elif t in ("bathroom", "toilet"):
        wc = _corner(r, "SW" if r.w >= r.h else "NW", 0.42, 0.62)
        taken.append(wc)
        out.append(Furniture("wc", room.id, wc.x, wc.y, wc.w, wc.h))
        basin = _corner(r, "SE" if r.w >= r.h else "NE", 0.55, 0.45)
        if _free(basin, taken, blocked):
            taken.append(basin)
            out.append(Furniture("basin", room.id, basin.x, basin.y, basin.w, basin.h))
        if t == "bathroom" and r.area >= 3.2:
            sh = _corner(r, "NE" if r.w >= r.h else "SE", 0.95, 0.95)
            if _free(sh, taken, blocked):
                taken.append(sh)
                out.append(Furniture("shower", room.id, sh.x, sh.y, sh.w, sh.h))

    elif t == "utility":
        place("washer", [N, S, E, W], 0.62, 0.62)
        place("sink", [W, E, S, N], 0.50, 0.60)

    elif t == "pooja":
        place("pooja_unit", [N, W, E, S], 0.45, min(1.10, max(r.w, r.h) * 0.8),
              {S: 0, N: 180, W: 90, E: 270}, required=True)

    elif t in ("study", "home_office"):
        place("desk", _sides_by_preference(r), 0.60, min(1.50, max(r.w, r.h) * 0.6),
              {S: 0, N: 180, W: 90, E: 270}, required=True)
        place("bookshelf", _sides_by_preference(r)[::-1], 0.35, min(1.60, max(r.w, r.h) * 0.6),
              {S: 0, N: 180, W: 90, E: 270})

    elif t == "store":
        place("shelving", [N, W, E, S], 0.45, min(1.80, max(r.w, r.h) * 0.85),
              {S: 0, N: 180, W: 90, E: 270}, required=True)

    elif t == "foyer":
        place("shoe_rack", [W, E, N, S], 0.35, min(1.10, max(r.w, r.h) * 0.5),
              {S: 0, N: 180, W: 90, E: 270})

    # ---- parking ----------------------------------------------------------
    elif t == "parking":
        cars = max(1, int(round(r.w / 2.75)) if r.w >= r.h else int(round(r.h / 2.75)))
        for i in range(cars):
            if r.w >= r.h:
                bay_w = r.w / cars
                car = Rect(r.x + i * bay_w + bay_w / 2 - 0.90, r.cy - 2.10, 1.80, 4.20)
                rot = 0
            else:
                bay_h = r.h / cars
                car = Rect(r.cx - 2.10, r.y + i * bay_h + bay_h / 2 - 0.90, 4.20, 1.80)
                rot = 90
            car = Rect(max(car.x, r.x + 0.05), max(car.y, r.y + 0.05),
                       min(car.w, r.w - 0.10), min(car.h, r.h - 0.10))
            if car.w > 0.5 and car.h > 0.5:
                out.append(Furniture("car", room.id, car.x, car.y, car.w, car.h, rot))

    # ---- staircase --------------------------------------------------------
    elif t == "staircase":
        out.append(Furniture("stair", room.id, r.x, r.y, r.w, r.h,
                             0 if r.h >= r.w else 90))

    return out


def furnish(rooms: list, doors: list) -> list[Furniture]:
    """Furnish every room, giving each one only the doors on its own floor."""
    doors_by_floor: dict[int, list] = {}
    for d in doors:
        doors_by_floor.setdefault(d.floor, []).append(d)

    out: list[Furniture] = []
    for room in rooms:
        try:
            out.extend(furnish_room(room, doors_by_floor.get(room.floor, [])))
        except Exception:
            # Furniture is presentation, never a reason to fail a plan.
            continue
    return out
