"""
The spatial solver.

Approach: an adjacency-driven slicing tree, searched by seeded multi-restart.

  1. Fixed cores (staircase, parking bay) are anchored to the envelope boundary
     and reserved. The staircase keeps an identical footprint on every level, so
     the floors actually stack.
  2. The remaining spaces are put into a chain by affinity seriation, so spaces
     that should touch end up next to each other in the sequence.
  3. The chain is recursively cut with guillotine splits. Because a slicing tree
     partitions exactly, the floor is always filled with no gaps and no overlaps,
     which is what makes the areas, the wall network and the 3D extrusion exact.
  4. Steps 2 and 3 are repeated with different seeds and the candidates are
     scored on relationships, proportion, area fidelity, daylight and privacy.
     The best-scoring plan wins.

The search is deterministic: the same requirements always produce the same plan,
which matters when a user nudges one slider and expects the plan to stay
recognisable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .geometry import Rect, exterior_edges, split_rect, subtract
from .program import Programme, SpaceReq
from .standards import (
    MAX_BALCONY_PROJECTION_RATIO, STAIR_LENGTH, STAIR_WIDTH,
    adjacency_weight, spec,
)
from .topology import build_contacts, evaluate_relationships

ANCHORS = ["SW", "SE", "NW", "NE", "S", "N", "W", "E"]
PARKING_ANCHORS = ["SW", "SE"]   # a bay centred on the frontage splits the plan
MIN_STRIP = 1.7          # a leftover strip thinner than this is not usable space
DEFAULT_RESTARTS = 500


@dataclass
class PlacedRoom:
    """A programme space that now has a rectangle."""
    id: str
    type: str
    label: str
    floor: int
    rect: Rect
    zone: str
    color: str
    priority: int
    habitable: bool
    wet: bool
    target_area: float
    min_area: float
    min_dim: float
    max_area: float
    aspect_max: float
    attached_to: str | None = None
    host_id: str | None = None
    note: str = ""
    fixed: bool = False

    @property
    def area(self) -> float:
        return self.rect.area

    def as_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "label": self.label, "floor": self.floor,
            "zone": self.zone, "color": self.color, "note": self.note,
            "x": round(self.rect.x, 3), "y": round(self.rect.y, 3),
            "w": round(self.rect.w, 3), "h": round(self.rect.h, 3),
            "area": round(self.rect.area, 2),
            "target_area": round(self.target_area, 2),
            "min_area": self.min_area, "min_dim": self.min_dim,
            "aspect": round(self.rect.aspect, 2),
            "habitable": self.habitable, "wet": self.wet,
            "attached_to": self.attached_to, "host_id": self.host_id,
        }


def _from_req(s: SpaceReq, rect: Rect) -> PlacedRoom:
    st = spec(s.type)
    return PlacedRoom(
        id=s.id, type=s.type, label=s.label, floor=s.floor, rect=rect,
        zone=s.zone, color=s.color, priority=s.priority, habitable=s.habitable,
        wet=s.wet, target_area=s.target_area, min_area=s.min_area,
        min_dim=s.min_dim, max_area=s.max_area, aspect_max=st["aspect_max"],
        attached_to=s.attached_to, host_id=s.host_id, note=s.note, fixed=s.fixed,
    )


# --------------------------------------------------------------------------
# Fixed-core placement
# --------------------------------------------------------------------------
def anchor_rect(env: Rect, w: float, h: float, anchor: str) -> Rect:
    """Place a fixed footprint against the envelope at one of eight anchors."""
    w = min(w, env.w)
    h = min(h, env.h)

    if "W" in anchor:
        x = env.x
    elif "E" in anchor:
        x = env.x2 - w
    else:
        x = env.cx - w / 2.0

    if "S" in anchor:
        y = env.y
    elif "N" in anchor:
        y = env.y2 - h
    else:
        y = env.cy - h / 2.0

    return _deslive(Rect(x, y, w, h), env)


def _deslive(r: Rect, env: Rect) -> Rect:
    """
    Shift a reserved rectangle flush against the envelope when it would otherwise
    leave an unusably thin strip behind it. Shifting (rather than growing) keeps
    the reserved space at its designed size.
    """
    x, y, w, h = r.x, r.y, r.w, r.h

    gap_w = x - env.x
    gap_e = env.x2 - (x + w)
    if 0 < gap_w < MIN_STRIP:
        x = env.x
    elif 0 < gap_e < MIN_STRIP:
        x = env.x2 - w

    gap_s = y - env.y
    gap_n = env.y2 - (y + h)
    if 0 < gap_s < MIN_STRIP:
        y = env.y
    elif 0 < gap_n < MIN_STRIP:
        y = env.y2 - h

    return Rect(x, y, w, h)


def carve_all(free: list[Rect], hole: Rect) -> list[Rect]:
    out: list[Rect] = []
    for f in free:
        out.extend(subtract(f, hole))
    return out


# --------------------------------------------------------------------------
# Affinity seriation
# --------------------------------------------------------------------------
def seriate(items: list[SpaceReq], rng: random.Random, temp: float = 0.0) -> list[SpaceReq]:
    """
    Order spaces into a chain where consecutive entries want to be adjacent.

    A slicing tree keeps sequence neighbours geometrically close, so getting this
    order right is most of what makes the relationships come out correct.
    `temp` injects controlled randomness so different seeds explore different
    orders.
    """
    if len(items) <= 2:
        return list(items)

    remaining = list(items)
    # Start from the space that anchors circulation, then the biggest public room.
    remaining.sort(key=lambda s: (-s.priority, -s.target_area))
    start = next((s for s in remaining if s.type == "parking"), None) \
        or next((s for s in remaining if s.type == "foyer"), None) \
        or next((s for s in remaining if s.type == "staircase"), None) \
        or remaining[0]

    chain = [start]
    remaining.remove(start)

    while remaining:
        cur = chain[-1]
        scored = []
        for cand in remaining:
            w, required, _ = adjacency_weight(cur.type, cand.type)
            s = w + (4.0 if required else 0.0)
            # Keep an en-suite immediately after its bedroom.
            if cand.attached_to == cur.id or cur.attached_to == cand.id:
                s += 25.0
            # Mild pull towards similar size, which produces better proportions.
            s -= 0.12 * abs(cand.target_area - cur.target_area)
            if temp:
                s += rng.gauss(0.0, temp)
            scored.append((s, cand))
        scored.sort(key=lambda t: -t[0])
        nxt = scored[0][1]
        chain.append(nxt)
        remaining.remove(nxt)

    return chain


# --------------------------------------------------------------------------
# Guillotine partition
# --------------------------------------------------------------------------
def _group_min_dim(items: list[SpaceReq]) -> float:
    return max((i.min_dim for i in items), default=0.5)


def _feasible_frac(rect: Rect, vertical: bool, frac: float,
                   left: list[SpaceReq], right: list[SpaceReq]) -> float:
    """Clamp a split ratio so neither side drops below its group's minimum width."""
    span = rect.w if vertical else rect.h
    if span <= 0:
        return 0.5
    lo = _group_min_dim(left) / span
    hi = 1.0 - _group_min_dim(right) / span
    if lo > hi:
        return 0.5
    return min(max(frac, lo), hi)


def _split_penalty(r: Rect, items: list[SpaceReq], env: Rect | None = None) -> float:
    """How badly a sub-rectangle serves the group assigned to it."""
    need = _group_min_dim(items)
    pen = 0.0
    if r.short_side < need:
        pen += (need - r.short_side) * 8.0
    # A single room inherits the rectangle's proportion directly.
    limit = spec(items[0].type)["aspect_max"] if len(items) == 1 else 3.0
    if r.aspect > limit:
        pen += (r.aspect - limit) * 1.5
    want = sum(i.target_area for i in items)
    if want > 0:
        pen += abs(r.area - want) / want
    return pen


def slice_into(rect: Rect, items: list[SpaceReq], rng: random.Random,
               jitter: float = 0.0, env: Rect | None = None) -> list[tuple[SpaceReq, Rect]]:
    """Recursively cut `rect` so each item in `items` gets a sub-rectangle."""
    if not items:
        return []
    if len(items) == 1:
        return [(items[0], rect)]

    total = sum(i.target_area for i in items) or 1.0

    # Candidate cut points, ordered by how evenly they divide the area. Trying
    # several rather than only the most balanced one matters: the balanced cut
    # sometimes hands a single wide room an unusably shallow strip, and a
    # slightly lopsided cut elsewhere in the chain avoids that entirely.
    cuts: list[tuple[float, int, float]] = []
    acc = 0.0
    for k in range(1, len(items)):
        acc += items[k - 1].target_area
        cuts.append((abs(acc / total - 0.5), k, acc))
    cuts.sort(key=lambda t: t[0])
    cuts = cuts[:4]

    scored: list[tuple[float, int, Rect, Rect]] = []
    for _bal, k, left_area in cuts:
        left, right = items[:k], items[k:]
        frac = left_area / total
        for vertical in (True, False):
            f = _feasible_frac(rect, vertical, frac, left, right)
            r1, r2 = split_rect(rect, vertical, f)
            pen = _split_penalty(r1, left, env) + _split_penalty(r2, right, env)
            # Cutting across the long axis keeps pieces closer to square.
            if (vertical and rect.w < rect.h) or (not vertical and rect.h < rect.w):
                pen += 0.35
            # Mild preference for the balanced cut, all else being equal.
            pen += _bal * 0.6
            scored.append((pen, k, r1, r2))

    scored.sort(key=lambda t: t[0])
    if jitter > 0 and len(scored) > 1 and rng.random() < jitter:
        pick = rng.choice(scored[:min(3, len(scored))])
    else:
        pick = scored[0]

    _, k, r1, r2 = pick
    left, right = items[:k], items[k:]
    return (slice_into(r1, left, rng, jitter, env)
            + slice_into(r2, right, rng, jitter, env))


def _distribute(items: list[SpaceReq], free: list[Rect]) -> list[list[SpaceReq]]:
    """
    Split the ordered chain across several free regions.

    Free regions are spatially disjoint, so every cut in the chain severs a
    relationship: whichever two spaces straddle it will not end up adjacent.
    Cutting purely on area is what puts the parking bay between the kitchen and
    the dining room. So each cut is placed near its area-proportional position
    but nudged to whichever nearby link is weakest, and required relationships
    are treated as effectively uncuttable.
    """
    n_reg = len(free)
    if n_reg <= 1 or len(items) <= 1:
        return [items]
    if len(items) < n_reg:
        return [[it] for it in items] + [[] for _ in range(n_reg - len(items))]

    total_free = sum(r.area for r in free) or 1.0
    total_items = sum(i.target_area for i in items) or 1.0

    cumulative: list[float] = []
    acc = 0.0
    for it in items:
        acc += it.target_area
        cumulative.append(acc)

    cuts: list[int] = []
    area_frac = 0.0
    low = 0
    for ri in range(n_reg - 1):
        area_frac += free[ri].area / total_free
        target = area_frac * total_items
        ideal = next((i + 1 for i, c in enumerate(cumulative) if c >= target), len(items) - 1)

        # Leave at least one space for this region and for every region after it.
        lo = low + 1
        hi = len(items) - (n_reg - 1 - ri)
        if lo > hi:
            lo = hi
        ideal = min(max(ideal, lo), hi)

        best: tuple[float, int] | None = None
        for j in range(max(lo, ideal - 2), min(hi, ideal + 2) + 1):
            weight, required, _ = adjacency_weight(items[j - 1].type, items[j].type)
            penalty = max(weight, 0.0) + (25.0 if required else 0.0) + 0.6 * abs(j - ideal)
            if best is None or penalty < best[0]:
                best = (penalty, j)

        cut = best[1] if best else ideal
        cuts.append(cut)
        low = cut

    chunks: list[list[SpaceReq]] = []
    prev = 0
    for c in cuts:
        chunks.append(items[prev:c])
        prev = c
    chunks.append(items[prev:])
    return chunks


# --------------------------------------------------------------------------
# Floor and building assembly
# --------------------------------------------------------------------------
def layout_floor(envelope: Rect, spaces: list[SpaceReq],
                 reserved: list[tuple[SpaceReq, Rect]], rng: random.Random,
                 temp: float, jitter: float) -> list[PlacedRoom]:
    reserved_ids = {s.id for s, _ in reserved}
    placed: list[PlacedRoom] = [_from_req(s, r) for s, r in reserved]

    free: list[Rect] = [envelope]
    for _, r in reserved:
        free = carve_all(free, r)

    flex = [s for s in spaces if s.id not in reserved_ids]
    if not free:
        return placed
    if not flex:
        # Nothing left to place: fill the leftovers with circulation.
        for n, r in enumerate(free):
            placed.append(_corridor(r, spaces[0].floor if spaces else 0, n))
        return placed

    # Work through regions front-to-back so the chain stays spatially coherent.
    free.sort(key=lambda r: (round(r.y, 2), round(r.x, 2)))
    # More regions than spaces would leave dead pockets; keep the biggest.
    if len(free) > len(flex):
        free = sorted(free, key=lambda r: -r.area)[:len(flex)]
        free.sort(key=lambda r: (round(r.y, 2), round(r.x, 2)))

    chain = seriate(flex, rng, temp)
    chunks = _distribute(chain, free)

    floor_level = flex[0].floor
    for n, (region, group) in enumerate(zip(free, chunks)):
        if not group:
            placed.append(_corridor(region, floor_level, n))
            continue
        for s, r in slice_into(region, group, rng, jitter, envelope):
            placed.append(_from_req(s, r))

    return placed


def _corridor(r: Rect, floor: int, n: int) -> PlacedRoom:
    st = spec("corridor")
    return PlacedRoom(
        id=f"corridor_{floor}_{n}", type="corridor", label="Lobby", floor=floor,
        rect=r, zone=st["zone"], color=st["color"], priority=st["priority"],
        habitable=False, wet=False, target_area=r.area, min_area=st["min_area"],
        min_dim=st["min_dim"], max_area=st["max_area"], aspect_max=st["aspect_max"],
        note="Circulation pocket left by the fixed cores",
    )


# --------------------------------------------------------------------------
# Local repair: widen rooms that came out below their minimum dimension
# --------------------------------------------------------------------------
FIXED_CORES = {"staircase", "parking"}


def _slack(d: PlacedRoom, axis: str) -> float:
    """How much a room can give away on one axis before it becomes unusable."""
    if d.fixed or d.type in FIXED_CORES:
        return 0.0
    rc = d.rect
    if axis == "x":
        by_dim = rc.w - d.min_dim
        by_area = rc.w - (d.min_area / rc.h if rc.h > 1e-6 else 0.0)
    else:
        by_dim = rc.h - d.min_dim
        by_area = rc.h - (d.min_area / rc.w if rc.w > 1e-6 else 0.0)
    return max(0.0, min(by_dim, by_area))


def _donors(rooms: list[PlacedRoom], r: PlacedRoom, axis: str,
            direction: int, tol: float) -> list[PlacedRoom] | None:
    """
    Rooms that sit against one face of `r` and could cede width to it.

    A rectangle can only shrink uniformly, so a donor is usable only if its own
    cross-axis span sits entirely within `r`'s span. The donors must also tile
    that face completely, otherwise moving the boundary would tear a hole in the
    floor plate.
    """
    rc = r.rect
    if axis == "x":
        boundary = rc.x if direction < 0 else rc.x2
        lo, hi = rc.y, rc.y2
    else:
        boundary = rc.y if direction < 0 else rc.y2
        lo, hi = rc.x, rc.x2

    sel: list[PlacedRoom] = []
    for d in rooms:
        if d is r or d.floor != r.floor:
            continue
        dc = d.rect
        if axis == "x":
            edge = dc.x2 if direction < 0 else dc.x
            d_lo, d_hi = dc.y, dc.y2
        else:
            edge = dc.y2 if direction < 0 else dc.y
            d_lo, d_hi = dc.x, dc.x2
        if abs(edge - boundary) > tol:
            continue
        if d_hi <= lo + tol or d_lo >= hi - tol:
            continue
        if d_lo < lo - tol or d_hi > hi + tol:
            return None       # donor overhangs the face: cannot shrink cleanly
        sel.append(d)

    if not sel:
        return None
    cover = 0.0
    for d in sel:
        dc = d.rect
        d_lo, d_hi = (dc.y, dc.y2) if axis == "x" else (dc.x, dc.x2)
        cover += min(d_hi, hi) - max(d_lo, lo)
    if abs(cover - (hi - lo)) > tol * 2:
        return None           # face not fully tiled
    return sel


def _widen(rooms: list[PlacedRoom], r: PlacedRoom, axis: str, direction: int,
           need: float, tol: float) -> bool:
    donors = _donors(rooms, r, axis, direction, tol)
    if not donors:
        return False
    shift = min([need] + [_slack(d, axis) for d in donors])
    if shift < 0.02:
        return False

    rc = r.rect
    if axis == "x":
        r.rect = Rect(rc.x - shift, rc.y, rc.w + shift, rc.h) if direction < 0 \
            else Rect(rc.x, rc.y, rc.w + shift, rc.h)
        for d in donors:
            dc = d.rect
            d.rect = Rect(dc.x, dc.y, dc.w - shift, dc.h) if direction < 0 \
                else Rect(dc.x + shift, dc.y, dc.w - shift, dc.h)
    else:
        r.rect = Rect(rc.x, rc.y - shift, rc.w, rc.h + shift) if direction < 0 \
            else Rect(rc.x, rc.y, rc.w, rc.h + shift)
        for d in donors:
            dc = d.rect
            d.rect = Rect(dc.x, dc.y, dc.w, dc.h - shift) if direction < 0 \
                else Rect(dc.x, dc.y + shift, dc.w, dc.h - shift)
    return True


def fit_score(r: PlacedRoom, rect: Rect) -> float:
    """
    How well a rectangle serves a particular room, in 0..1.

    The over-size term matters as much as the under-size one. Without it the
    repair passes will cheerfully park a 2 m2 powder room in the best 11 m2
    rectangle on the floor to win an adjacency, because nothing was charging
    them for the waste - and the living room ends up in the leftover strip.
    """
    t = 1.0
    if rect.short_side < r.min_dim:
        t *= max(0.0, 1.0 - 2.2 * (r.min_dim - rect.short_side) / max(r.min_dim, 0.1))
    if rect.area < r.min_area:
        t *= max(0.0, 1.0 - 1.6 * (r.min_area - rect.area) / max(r.min_area, 0.1))
    if r.max_area > 0 and rect.area > r.max_area:
        t *= max(0.20, 1.0 - (rect.area - r.max_area) / max(r.max_area, 0.1))
    if rect.aspect > r.aspect_max:
        t *= max(0.3, 1.0 - (rect.aspect - r.aspect_max) / 3.0)
    if r.target_area > 0:
        t *= max(0.15, 1.0 - min(1.0, abs(rect.area - r.target_area) / r.target_area / 1.2))
    return t


def _neighbours(rooms: list[PlacedRoom], target: PlacedRoom,
                exclude: PlacedRoom) -> list[PlacedRoom]:
    """Rooms sharing a wall with target's rectangle, ignoring one room."""
    from .geometry import shared_edge
    out = []
    for r in rooms:
        if r is target or r is exclude or r.floor != target.floor:
            continue
        e = shared_edge(target.rect, r.rect)
        if e is not None and e.length >= 0.5:
            out.append(r)
    return out


def _local_affinity(space_type: str, neighbours: list[PlacedRoom]) -> float:
    return sum(adjacency_weight(space_type, n.type)[0] for n in neighbours)


def repair_swaps(rooms: list[PlacedRoom], passes: int = 3,
                 min_gain: float = 0.15) -> int:
    """
    Exchange two rooms' rectangles when the swap makes both fit better without
    damaging their relationships.

    The slicing tree fixes which rectangle each position in the chain gets, but
    not which room suits which rectangle. A tall narrow slot that fails a living
    room may suit a store perfectly, and trading the two costs nothing
    geometrically. The affinity term is essential: without it the pass happily
    buys proportion by moving the kitchen away from the dining room.
    """
    swaps = 0
    for _ in range(passes):
        improved = False
        broken = [r for r in rooms
                  if not r.fixed and r.type not in FIXED_CORES
                  and (r.rect.short_side < r.min_dim - 1e-3
                       or r.rect.area < r.min_area - 1e-3)]
        for r in broken:
            for o in rooms:
                if o is r or o.floor != r.floor or o.fixed or o.type in FIXED_CORES:
                    continue

                fit_before = fit_score(r, r.rect) + fit_score(o, o.rect)
                fit_after = fit_score(r, o.rect) + fit_score(o, r.rect)
                if fit_after <= fit_before + min_gain:
                    continue

                # Neighbours belong to the rectangles, not the rooms, so a swap
                # simply exchanges which neighbour set each room inherits.
                nr = _neighbours(rooms, r, o)
                no = _neighbours(rooms, o, r)
                rel_before = _local_affinity(r.type, nr) + _local_affinity(o.type, no)
                rel_after = _local_affinity(r.type, no) + _local_affinity(o.type, nr)

                if (fit_after - fit_before) + 0.05 * (rel_after - rel_before) > min_gain:
                    r.rect, o.rect = o.rect, r.rect
                    swaps += 1
                    improved = True
                    break
        if not improved:
            break
    return swaps


def repair_dimensions(rooms: list[PlacedRoom], passes: int = 5, tol: float = 0.02) -> int:
    """
    Nudge shared walls so undersized rooms reach their minimum clear dimension,
    taking the space from neighbours that can spare it.

    The slicing tree optimises globally but can still leave one room a little too
    narrow. Moving a single partition is a far better fix than rejecting an
    otherwise good plan, and because only shared boundaries move, the floor plate
    stays exactly tiled.
    """
    fixes = 0
    for _ in range(passes):
        changed = False
        for r in sorted(rooms, key=lambda r: -r.priority):
            if r.fixed or r.type in FIXED_CORES or r.type == "terrace":
                continue
            for axis in ("x", "y"):
                span = r.rect.w if axis == "x" else r.rect.h
                need = r.min_dim - span
                if need <= 1e-3:
                    continue
                for direction in (-1, 1):
                    if _widen(rooms, r, axis, direction, need, tol):
                        changed = True
                        fixes += 1
                        break
        if not changed:
            break
    return fixes


def _feasibility_of(rooms: list[PlacedRoom]) -> float:
    terms = [fit_score(r, r.rect) for r in rooms
             if r.type not in ("corridor", "terrace") and not r.fixed]
    if not terms:
        return 1.0
    return 0.5 * sum(terms) / len(terms) + 0.5 * min(terms)


def plan_objective(rooms: list[PlacedRoom], envelope: Rect | None = None) -> float:
    """
    Objective for the repair search.

    Daylight is included because the repair moves rooms between rectangles: left
    out, it happily fixes an adjacency by swapping a bedroom into the middle of
    the plan, trading a warning for a worse error. Required adjacencies are
    weighted well above preferred ones, since those are the ones that fail
    validation rather than merely reading as awkward.
    """
    rel = evaluate_relationships(rooms, build_contacts(rooms))
    rel_s = max(0.0, min(1.0,
                         0.90 * rel["required_score"]
                         + 0.10 * rel["preferred_score"]
                         - 0.10 * rel["violation_count"]))

    day = 1.0
    if envelope is not None:
        hab = [r for r in rooms if r.habitable]
        if hab:
            lit = sum(1 for r in hab if exterior_edges(r.rect, envelope))
            day = lit / len(hab)

    return 0.55 * rel_s + 0.25 * _feasibility_of(rooms) + 0.20 * day


def repair_relationships(rooms: list[PlacedRoom], envelope: Rect | None = None,
                         sweeps: int = 6) -> int:
    """
    Hill-climb on room-to-rectangle assignment to recover broken relationships.

    A slicing tree guarantees a clean partition but not that the two spaces on
    either side of a cut actually touch, so some required adjacencies come out
    unsatisfied however good the chain order was. Swapping which room occupies
    which rectangle changes the adjacency graph without touching the geometry at
    all, which makes it a cheap and completely safe move: the floor stays exactly
    tiled no matter what the search does.

    This is deliberately run only on the finalists, since it is far more
    expensive per candidate than the phase-one score.
    """
    moves = 0
    floors = sorted({r.floor for r in rooms})

    for floor in floors:
        group = [r for r in rooms
                 if r.floor == floor and not r.fixed and r.type not in FIXED_CORES]
        if len(group) < 2:
            continue

        current = plan_objective(rooms, envelope)
        for _ in range(sweeps):
            improved = False
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    a.rect, b.rect = b.rect, a.rect
                    trial = plan_objective(rooms, envelope)
                    if trial > current + 1e-4:
                        current = trial
                        moves += 1
                        improved = True
                    else:
                        a.rect, b.rect = b.rect, a.rect   # revert
            if not improved:
                break
    return moves


@dataclass
class Candidate:
    seed: int
    rooms: list[PlacedRoom]
    stair_rect: Rect | None
    parking_rect: Rect | None
    score: float = 0.0
    breakdown: dict = field(default_factory=dict)


def layout_building(prog: Programme, envelope: Rect, seed: int) -> Candidate:
    rng = random.Random(seed)
    temp = rng.choice([0.0, 0.0, 1.2, 2.5, 4.0])
    jitter = rng.choice([0.0, 0.0, 0.3, 0.6])

    # --- parking: must reach the street, so it hugs the front edge -----------
    parking_rect: Rect | None = None
    parking_req = next((s for f in prog.floors for s in f.spaces if s.type == "parking"), None)
    if parking_req is not None:
        pw = min(parking_req.fixed_w, envelope.w)
        ph = min(parking_req.fixed_h, envelope.h * 0.6)
        parking_rect = anchor_rect(envelope, pw, ph, rng.choice(PARKING_ANCHORS))

    # --- staircase: one footprint shared by every level ----------------------
    # Anchored inside what the parking bay leaves free rather than against the
    # envelope, so the two reserved cores can never overlap on a tight plot.
    stair_rect: Rect | None = None
    if any(s.type == "staircase" for f in prog.floors for s in f.spaces):
        sw = min(STAIR_WIDTH, envelope.w)
        sh = min(STAIR_LENGTH, envelope.h)
        regions = carve_all([envelope], parking_rect) if parking_rect else [envelope]
        hosts = [r for r in regions if r.w >= sw - 1e-6 and r.h >= sh - 1e-6]
        if hosts:
            base = max(hosts, key=lambda r: r.area)
            stair_rect = anchor_rect(base, sw, sh, rng.choice(ANCHORS))
        else:
            # Nothing fits: take the largest free region and shrink the core into
            # it. The validator reports the undersized stair rather than letting
            # it silently overlap the parking bay.
            base = max(regions, key=lambda r: r.area) if regions else envelope
            stair_rect = anchor_rect(base, min(sw, base.w), min(sh, base.h),
                                     rng.choice(ANCHORS))

    rooms: list[PlacedRoom] = []
    for fp in prog.floors:
        reserved: list[tuple[SpaceReq, Rect]] = []
        for s in fp.spaces:
            if s.type == "staircase" and stair_rect is not None:
                reserved.append((s, stair_rect))
            elif s.type == "parking" and parking_rect is not None:
                reserved.append((s, parking_rect))
        floor_rooms = layout_floor(envelope, fp.spaces, reserved, rng, temp, jitter)
        repair_swaps(floor_rooms)
        repair_dimensions(floor_rooms)
        repair_swaps(floor_rooms)
        rooms.extend(floor_rooms)

    for r in rooms:
        r.rect = r.rect.snapped()

    return Candidate(seed=seed, rooms=rooms, stair_rect=stair_rect, parking_rect=parking_rect)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
WEIGHTS = {
    "relationships": 0.26,
    "feasibility": 0.24,
    "entrance": 0.10,
    "proportion": 0.10,
    "area_fit": 0.10,
    "daylight": 0.12,
    "privacy": 0.05,
    "circulation": 0.03,
}


def score_candidate(cand: Candidate, envelope: Rect,
                    reach: dict | None = None) -> tuple[float, dict]:
    rooms = cand.rooms
    contacts = build_contacts(rooms)
    rel = evaluate_relationships(rooms, contacts)

    # -- relationships -------------------------------------------------------
    rel_score = 0.62 * rel["required_score"] + 0.38 * rel["preferred_score"]
    rel_score -= 0.10 * rel["violation_count"]
    rel_score = max(0.0, min(1.0, rel_score))

    # -- feasibility: a room below its minimum size or width is unusable, so
    #    this is scored as a hard pass/fail rather than a gentle penalty.
    feas_terms: list[float] = []
    for r in rooms:
        if r.type in ("corridor", "terrace"):
            continue
        t = 1.0
        if r.rect.short_side < r.min_dim - 1e-3:
            t *= max(0.0, 1.0 - 2.2 * (r.min_dim - r.rect.short_side) / max(r.min_dim, 0.1))
        if r.rect.area < r.min_area - 1e-3:
            t *= max(0.0, 1.0 - 1.6 * (r.min_area - r.rect.area) / max(r.min_area, 0.1))
        if r.max_area > 0 and r.rect.area > r.max_area * 1.7:
            # Generously past the cap: the space is being wasted on this room.
            t *= max(0.25, 1.0 - (r.rect.area - r.max_area * 1.7) / max(r.max_area, 0.1))
        feas_terms.append(t)
    # Blend the mean with the worst room: a plan with one unusable space is not
    # 94% feasible, and averaging alone would let the solver ship exactly that.
    feas_score = (0.5 * sum(feas_terms) / max(1, len(feas_terms))
                  + 0.5 * min(feas_terms, default=1.0))

    # -- proportion: how close rooms stay to a workable shape ----------------
    prop_terms: list[float] = []
    for r in rooms:
        over = r.rect.aspect - r.aspect_max
        prop_terms.append(1.0 if over <= 0 else max(0.0, 1.0 - min(1.0, over / 2.0)))
    prop_score = sum(prop_terms) / max(1, len(prop_terms))

    # -- area fidelity against the programme budget --------------------------
    area_terms = []
    for r in rooms:
        if r.target_area <= 0 or r.type == "corridor":
            continue
        err = abs(r.rect.area - r.target_area) / r.target_area
        area_terms.append(max(0.0, 1.0 - min(1.0, err / 0.55)))
    area_score = sum(area_terms) / max(1, len(area_terms))

    # -- daylight: habitable rooms need an external wall ---------------------
    day_terms = []
    for r in rooms:
        if not r.habitable:
            continue
        day_terms.append(1.0 if exterior_edges(r.rect, envelope) else 0.0)
    day_score = sum(day_terms) / max(1, len(day_terms))

    # -- privacy: bedrooms should not open straight off the entrance ---------
    priv = 1.0
    foyer_ids = {r.id for r in rooms if r.type == "foyer"}
    park_ids = {r.id for r in rooms if r.type == "parking"}
    beds = [r for r in rooms if r.type in ("bedroom", "master_bedroom", "guest_bedroom")]
    if beds:
        bad = 0
        for c in contacts:
            if (c.a in foyer_ids or c.b in foyer_ids or c.a in park_ids or c.b in park_ids):
                other = c.b if (c.a in foyer_ids or c.a in park_ids) else c.a
                if any(b.id == other for b in beds):
                    bad += 1
        priv = max(0.0, 1.0 - bad / len(beds))

    # -- entrance: the front door has to land on a street-facing wall --------
    # Without this the solver will happily bury the foyer in the middle of the
    # plan, producing a house with no way in.
    entry_score = 1.0
    candidates = [r for r in rooms if r.floor == 0 and r.type in ("foyer", "living")]
    if candidates:
        # Score the best available entry, not only the foyer: a landlocked foyer
        # is acceptable when the living room fronts the street, and unacceptable
        # when nothing does.
        best_entry = 0.0
        for c in candidates:
            edges = exterior_edges(c.rect, envelope)
            front = [e for e in edges
                     if e.orientation == "h" and abs(e.y1 - envelope.y) < 0.03 and e.length >= 1.2]
            side = [e for e in edges
                    if e.orientation == "v" and e.length >= 1.2]
            if front:
                v = 1.0                       # opens onto the street frontage
            elif side:
                v = 0.62                      # entered down the side of the house
            elif edges:
                v = 0.3                       # only the rear wall is available
            else:
                v = 0.0                       # landlocked
            if c.type == "foyer":
                v *= 1.0
            else:
                v *= 0.85                     # entering straight into the living room
            best_entry = max(best_entry, v)
        entry_score = best_entry

    circ = reach["ratio"] if reach else 1.0

    parts = {
        "relationships": rel_score,
        "feasibility": feas_score,
        "entrance": entry_score,
        "proportion": prop_score,
        "area_fit": area_score,
        "daylight": day_score,
        "privacy": priv,
        "circulation": circ,
    }
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return total, {"parts": parts, "weights": WEIGHTS, "relationships": rel}


def solve(prog: Programme, envelope: Rect, restarts: int = DEFAULT_RESTARTS,
          finalists: int = 12) -> Candidate:
    """
    Two-phase search.

    Phase 1 scores many candidates on geometry and relationships alone, which is
    cheap. Phase 2 takes the best handful, actually places doors, and re-scores
    with real circulation. That keeps the search fast without letting a plan win
    on paper while being unwalkable.
    """
    from .topology import place_doors, reachability_report  # local: avoids a cycle

    pool: list[tuple[float, Candidate, dict]] = []
    for seed in range(restarts):
        cand = layout_building(prog, envelope, seed)
        s, bd = score_candidate(cand, envelope)
        pool.append((s, cand, bd))

    pool.sort(key=lambda t: -t[0])

    best: tuple[float, Candidate, dict] | None = None
    for s, cand, _bd in pool[:finalists]:
        # Recover relationships the partition could not satisfy on its own, then
        # tidy any dimension that the reassignment left short.
        repair_relationships(cand.rooms, envelope)
        repair_dimensions(cand.rooms)

        contacts = build_contacts(cand.rooms)
        doors = place_doors(cand.rooms, contacts, envelope)
        report = reachability_report(cand.rooms, doors)
        ratio = (sum(v["ratio"] for v in report.values()) / len(report)) if report else 1.0
        s2, bd2 = score_candidate(cand, envelope, reach={"ratio": ratio})
        if best is None or s2 > best[0]:
            best = (s2, cand, bd2)

    assert best is not None
    score, cand, bd = best
    cand.score = score
    cand.breakdown = bd
    return cand


# --------------------------------------------------------------------------
# Balconies (cantilevered projections into the setback)
# --------------------------------------------------------------------------
def place_balconies(balcony_reqs: list[SpaceReq], rooms: list[PlacedRoom],
                    envelope: Rect, setbacks: dict) -> tuple[list[PlacedRoom], list[str]]:
    """
    Balconies project outwards from a host room's external wall into the setback,
    limited to half the setback depth, which is the usual bye-law allowance.
    """
    by_id = {r.id: r for r in rooms}
    out: list[PlacedRoom] = []
    notes: list[str] = []
    occupied: list[Rect] = []

    side_setback = {
        "S": setbacks.get("front", 0.0),
        "N": setbacks.get("rear", 0.0),
        "W": setbacks.get("left", 0.0),
        "E": setbacks.get("right", 0.0),
    }

    for b in balcony_reqs:
        host = by_id.get(b.host_id or "")
        if host is None:
            continue

        options: list[tuple[float, str, Rect]] = []
        for side in ("S", "N", "W", "E"):
            allowed = side_setback[side] * MAX_BALCONY_PROJECTION_RATIO
            depth = min(1.5, allowed)
            if depth < 0.9:
                continue

            hr = host.rect
            if side == "S" and abs(hr.y - envelope.y) < 0.03:
                width = min(hr.w, 3.6)
                rect = Rect(hr.cx - width / 2, hr.y - depth, width, depth)
            elif side == "N" and abs(hr.y2 - envelope.y2) < 0.03:
                width = min(hr.w, 3.6)
                rect = Rect(hr.cx - width / 2, hr.y2, width, depth)
            elif side == "W" and abs(hr.x - envelope.x) < 0.03:
                width = min(hr.h, 3.6)
                rect = Rect(hr.x - depth, hr.cy - width / 2, depth, width)
            elif side == "E" and abs(hr.x2 - envelope.x2) < 0.03:
                width = min(hr.h, 3.6)
                rect = Rect(hr.x2, hr.cy - width / 2, depth, width)
            else:
                continue

            if any(rect.overlap_area(o) > 0.02 for o in occupied):
                continue
            # Prefer the longest frontage, and the street side for living rooms.
            bonus = 1.0 if (side == "S" and host.type == "living") else 0.0
            options.append((rect.area + bonus, side, rect))

        if options:
            options.sort(key=lambda t: -t[0])
            _, side, rect = options[0]
            kind = f"Cantilevered {rect.short_side:.2f} m off {host.label}"
        else:
            # Shallow setbacks leave nothing to cantilever into, so recess the
            # balcony into the host room instead. This is how balconies are
            # normally handled on tight urban plots.
            inset = _inset_balcony(host, envelope, occupied)
            if inset is None:
                notes.append(
                    f"{b.label} was dropped: {host.label} has no external wall with "
                    f"room to project into, and recessing one would take it below "
                    f"its minimum usable size."
                )
                continue
            rect, kind = inset

        occupied.append(rect)
        st = spec("balcony")
        out.append(PlacedRoom(
            id=b.id, type="balcony", label=b.label, floor=b.floor,
            rect=rect.snapped(), zone=b.zone, color=b.color, priority=b.priority,
            habitable=False, wet=False, target_area=b.target_area,
            min_area=b.min_area, min_dim=b.min_dim, max_area=b.max_area,
            aspect_max=st["aspect_max"], host_id=host.id, note=kind,
        ))

    return out, notes


def _inset_balcony(host: PlacedRoom, envelope: Rect,
                   occupied: list[Rect]) -> tuple[Rect, str] | None:
    """
    Carve a recessed balcony off the host room's external wall, shrinking the
    host. Returns None when the host cannot spare the depth.
    """
    depth = 1.25
    best: tuple[float, Rect, Rect, str] | None = None

    for e in exterior_edges(host.rect, envelope):
        hr = host.rect
        if e.orientation == "h":
            on_front = abs(e.y1 - hr.y) < 0.02
            new_h = hr.h - depth
            if new_h < host.min_dim or hr.w * new_h < host.min_area:
                continue
            if on_front:
                bal = Rect(hr.x, hr.y, hr.w, depth)
                rest = Rect(hr.x, hr.y + depth, hr.w, new_h)
            else:
                bal = Rect(hr.x, hr.y2 - depth, hr.w, depth)
                rest = Rect(hr.x, hr.y, hr.w, new_h)
        else:
            on_left = abs(e.x1 - hr.x) < 0.02
            new_w = hr.w - depth
            if new_w < host.min_dim or new_w * hr.h < host.min_area:
                continue
            if on_left:
                bal = Rect(hr.x, hr.y, depth, hr.h)
                rest = Rect(hr.x + depth, hr.y, new_w, hr.h)
            else:
                bal = Rect(hr.x2 - depth, hr.y, depth, hr.h)
                rest = Rect(hr.x, hr.y, new_w, hr.h)

        if any(bal.overlap_area(o) > 0.02 for o in occupied):
            continue
        if best is None or bal.area > best[0]:
            best = (bal.area, bal, rest, f"Recessed balcony taken off {host.label}")

    if best is None:
        return None
    _, bal, rest, kind = best
    host.rect = rest        # the host gives up the strip
    return bal, kind
