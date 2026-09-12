"""
Rectangle algebra used by the layout solver.

The whole planner works on axis-aligned rectangles in metres, with the origin at
the front-left corner of the plot:

    x -> along the street frontage (plot width)
    y -> into the plot (plot depth); y = 0 is the street edge

Keeping every space rectangular is a deliberate constraint: it makes area,
adjacency, wall extraction and 3D extrusion exact rather than approximate, which
is what lets the 2D drawing and the 3D model be generated from one dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

from .standards import GRID

EPS = 1e-6


def snap(value: float, grid: float = GRID) -> float:
    """Snap a length to the construction grid to avoid sliver geometry."""
    return round(round(value / grid) * grid, 4)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    # -- derived -----------------------------------------------------------
    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def short_side(self) -> float:
        return min(self.w, self.h)

    @property
    def long_side(self) -> float:
        return max(self.w, self.h)

    @property
    def aspect(self) -> float:
        s = self.short_side
        return self.long_side / s if s > EPS else float("inf")

    @property
    def perimeter(self) -> float:
        return 2 * (self.w + self.h)

    # -- operations --------------------------------------------------------
    def snapped(self) -> "Rect":
        x, y = snap(self.x), snap(self.y)
        return Rect(x, y, snap(self.x2) - x, snap(self.y2) - y)

    def inset(self, d: float) -> "Rect":
        return Rect(self.x + d, self.y + d, max(0.0, self.w - 2 * d), max(0.0, self.h - 2 * d))

    def contains_rect(self, o: "Rect", tol: float = 1e-4) -> bool:
        return (o.x >= self.x - tol and o.y >= self.y - tol
                and o.x2 <= self.x2 + tol and o.y2 <= self.y2 + tol)

    def contains_point(self, px: float, py: float, tol: float = 1e-4) -> bool:
        return (self.x - tol <= px <= self.x2 + tol) and (self.y - tol <= py <= self.y2 + tol)

    def overlap_area(self, o: "Rect") -> float:
        ox = min(self.x2, o.x2) - max(self.x, o.x)
        oy = min(self.y2, o.y2) - max(self.y, o.y)
        return ox * oy if ox > 0 and oy > 0 else 0.0

    def as_dict(self) -> dict:
        return {"x": round(self.x, 3), "y": round(self.y, 3),
                "w": round(self.w, 3), "h": round(self.h, 3)}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Rect({self.x:.2f},{self.y:.2f} {self.w:.2f}x{self.h:.2f})"


def valid(r: Rect, min_side: float = 0.05) -> bool:
    return r.w > min_side and r.h > min_side


def subtract(outer: Rect, hole: Rect) -> list[Rect]:
    """
    outer minus hole, expressed as up to four non-overlapping rectangles.

    Used when a fixed element (staircase core, parking bay) is reserved out of a
    free region before the remaining programme is partitioned into it.
    """
    if outer.overlap_area(hole) <= EPS:
        return [outer]

    hx1, hy1 = max(outer.x, hole.x), max(outer.y, hole.y)
    hx2, hy2 = min(outer.x2, hole.x2), min(outer.y2, hole.y2)

    pieces: list[Rect] = []
    # band below the hole (full width)
    if hy1 - outer.y > EPS:
        pieces.append(Rect(outer.x, outer.y, outer.w, hy1 - outer.y))
    # band above the hole (full width)
    if outer.y2 - hy2 > EPS:
        pieces.append(Rect(outer.x, hy2, outer.w, outer.y2 - hy2))
    # left of the hole (only across the hole band)
    if hx1 - outer.x > EPS:
        pieces.append(Rect(outer.x, hy1, hx1 - outer.x, hy2 - hy1))
    # right of the hole (only across the hole band)
    if outer.x2 - hx2 > EPS:
        pieces.append(Rect(hx2, hy1, outer.x2 - hx2, hy2 - hy1))

    return [p for p in pieces if valid(p)]


@dataclass(frozen=True)
class Edge:
    """A shared (or exterior) wall segment between two spaces."""
    x1: float
    y1: float
    x2: float
    y2: float
    orientation: str      # "h" for horizontal, "v" for vertical

    @property
    def length(self) -> float:
        return abs(self.x2 - self.x1) + abs(self.y2 - self.y1)

    @property
    def mid(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def as_dict(self) -> dict:
        return {"x1": round(self.x1, 3), "y1": round(self.y1, 3),
                "x2": round(self.x2, 3), "y2": round(self.y2, 3),
                "orientation": self.orientation}


def shared_edge(a: Rect, b: Rect, tol: float = 0.02) -> Edge | None:
    """
    The wall segment two rectangles have in common, or None if they only touch at
    a corner / do not touch at all.

    tol absorbs floating point drift after grid snapping.
    """
    # a is left of b (vertical shared wall) or vice versa
    if abs(a.x2 - b.x) <= tol or abs(b.x2 - a.x) <= tol:
        x = a.x2 if abs(a.x2 - b.x) <= tol else b.x2
        lo, hi = max(a.y, b.y), min(a.y2, b.y2)
        if hi - lo > tol:
            return Edge(x, lo, x, hi, "v")

    # a is below b (horizontal shared wall) or vice versa
    if abs(a.y2 - b.y) <= tol or abs(b.y2 - a.y) <= tol:
        y = a.y2 if abs(a.y2 - b.y) <= tol else b.y2
        lo, hi = max(a.x, b.x), min(a.x2, b.x2)
        if hi - lo > tol:
            return Edge(lo, y, hi, y, "h")

    return None


def exterior_edges(room: Rect, envelope: Rect, tol: float = 0.02) -> list[Edge]:
    """Sides of a room that lie on the building envelope boundary."""
    out: list[Edge] = []
    if abs(room.x - envelope.x) <= tol:
        out.append(Edge(room.x, room.y, room.x, room.y2, "v"))
    if abs(room.x2 - envelope.x2) <= tol:
        out.append(Edge(room.x2, room.y, room.x2, room.y2, "v"))
    if abs(room.y - envelope.y) <= tol:
        out.append(Edge(room.x, room.y, room.x2, room.y, "h"))
    if abs(room.y2 - envelope.y2) <= tol:
        out.append(Edge(room.x, room.y2, room.x2, room.y2, "h"))
    return out


def split_rect(r: Rect, vertical: bool, frac: float) -> tuple[Rect, Rect]:
    """
    Guillotine cut. vertical=True cuts along x (producing left and right pieces);
    frac is the share of area going to the first piece.
    """
    frac = min(max(frac, 0.02), 0.98)
    if vertical:
        w1 = r.w * frac
        return Rect(r.x, r.y, w1, r.h), Rect(r.x + w1, r.y, r.w - w1, r.h)
    h1 = r.h * frac
    return Rect(r.x, r.y, r.w, h1), Rect(r.x, r.y + h1, r.w, r.h - h1)


def rects_overlap(rects: list[Rect], tol: float = 1e-3) -> list[tuple[int, int, float]]:
    """Every pair of rectangles with a non-trivial intersection (integrity check)."""
    hits: list[tuple[int, int, float]] = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a = rects[i].overlap_area(rects[j])
            if a > tol:
                hits.append((i, j, a))
    return hits


def segment_overlap(a1: float, a2: float, b1: float, b2: float) -> tuple[float, float] | None:
    """1-D interval intersection, or None when the intervals barely touch."""
    lo, hi = max(a1, b1), min(a2, b2)
    return (lo, hi) if hi - lo > EPS else None
