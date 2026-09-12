"""
Engine tests.

The invariants here are the ones that make the rest of the system trustworthy:
if the floor plate does not tile exactly, then the areas, the wall network, the
3D model and the cost are all wrong together. Run with:

    python tests/test_engine.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.brief import parse_brief                                # noqa: E402
from app.engine.geometry import Rect, rects_overlap, shared_edge, subtract  # noqa: E402
from app.engine.planner import generate_plan, normalise             # noqa: E402
from app.engine.program import auto_bathroom_count, distribute_bedrooms  # noqa: E402

FAILED: list[str] = []
PASSED = 0


def check(name, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  pass  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


# ---------------------------------------------------------------- geometry
def test_geometry():
    section("Geometry")
    r = Rect(0, 0, 4, 3)
    check("area", abs(r.area - 12) < 1e-9)
    check("aspect", abs(r.aspect - 4 / 3) < 1e-9)

    pieces = subtract(Rect(0, 0, 10, 10), Rect(0, 0, 3, 4))
    covered = sum(p.area for p in pieces)
    check("subtract at a corner conserves area", abs(covered - (100 - 12)) < 1e-6,
          f"got {covered}")
    check("subtract pieces do not overlap", not rects_overlap(pieces))

    pieces = subtract(Rect(0, 0, 10, 10), Rect(3, 3, 2, 2))
    covered = sum(p.area for p in pieces)
    check("subtract an interior hole conserves area", abs(covered - 96) < 1e-6,
          f"got {covered}")
    check("interior-hole pieces do not overlap", not rects_overlap(pieces))

    e = shared_edge(Rect(0, 0, 3, 3), Rect(3, 1, 3, 3))
    check("shared edge found", e is not None and abs(e.length - 2) < 1e-6,
          f"got {e}")
    check("corner touch is not a shared wall",
          shared_edge(Rect(0, 0, 3, 3), Rect(3, 3, 3, 3)) is None)


# ---------------------------------------------------------------- programme
def test_programme():
    section("Programme")
    check("2 bedrooms -> 2 bathrooms", auto_bathroom_count(2, 2) == 2)
    check("bathrooms never exceed bedrooms",
          all(auto_bathroom_count(b, f) <= b for b in range(1, 9) for f in range(1, 5)))

    for beds in range(0, 9):
        for floors in range(1, 5):
            per = distribute_bedrooms(beds, floors, False)
            check(f"bedrooms conserved ({beds} over {floors})", sum(per) == beds,
                  f"got {per}") if beds == 8 and floors == 4 else None
            assert sum(per) == beds, (beds, floors, per)
    check("bedroom distribution conserves the count across every combination", True)
    check("single storey keeps every bedroom on the ground",
          distribute_bedrooms(3, 1, False) == [3])
    check("ground bedroom is honoured",
          distribute_bedrooms(3, 2, True)[0] == 1)


# ---------------------------------------------------------------- brief parser
def test_brief_parser():
    section("Brief parser (offline fallback)")
    r = parse_brief("3BHK duplex on a 30x40 site, G+1, car parking, pooja room, "
                    "utility, two balconies, east facing")
    check("bedrooms from 3BHK", r.get("bedrooms") == 3, str(r.get("bedrooms")))
    check("plot 30x40 ft", r.get("plot_width") == 30 and r.get("plot_depth") == 40)
    check("units feet", r.get("units") == "ft")
    check("G+1 -> 2 floors", r.get("floors") == 2, str(r.get("floors")))
    check("parking detected", r.get("parking_cars") == 1)
    check("two balconies", r.get("balconies") == 2, str(r.get("balconies")))
    check("east facing", r.get("facing") == "E")
    check("extras found", {"pooja", "utility"} <= set(r.get("extras", [])),
          str(r.get("extras")))

    r2 = parse_brief("single storey 2 bedroom house on 9 x 12 metres, no parking")
    check("metric plot detected", r2.get("units") == "m", str(r2.get("units")))
    check("single storey", r2.get("floors") == 1)
    check("no parking", r2.get("parking_cars") == 0)
    check("two bedrooms", r2.get("bedrooms") == 2)

    r3 = parse_brief("4BHK G+2 on 40 by 60 feet with two cars and a study, premium")
    check("G+2 -> 3 floors", r3.get("floors") == 3, str(r3.get("floors")))
    check("two cars", r3.get("parking_cars") == 2, str(r3.get("parking_cars")))
    check("premium quality", r3.get("quality") == "premium")


# ---------------------------------------------------------------- normalise
def test_normalise():
    section("Input hardening")
    bad = normalise({"plot_width": "abc", "plot_depth": None, "floors": 99,
                     "bedrooms": -5, "extras": ["pooja", "swimming_pool"],
                     "parking_type": "teleport", "units": "furlongs"})
    check("bad numbers fall back to defaults", bad["plot_width"] > 0)
    check("floors clamped to 4", bad["floors"] == 4, str(bad["floors"]))
    check("bedrooms clamped to 0", bad["bedrooms"] == 0, str(bad["bedrooms"]))
    check("unknown extras dropped", bad["extras"] == ["pooja"], str(bad["extras"]))
    check("invalid parking type rejected", bad["parking_type"] == "covered")
    check("invalid units rejected", bad["units"] == "ft")

    huge = normalise({"plot_width": 100000, "plot_depth": 100000, "units": "m"})
    check("plot size capped", huge["plot_width"] <= 120 and huge["plot_depth"] <= 150)


# ---------------------------------------------------------------- full plans
CASES = [
    ("3BHK G+1 on 30x40", dict(plot_width=30, plot_depth=40, floors=2, bedrooms=3,
                               parking_cars=1, balconies=2, extras=["pooja", "utility"])),
    ("2BHK single storey", dict(plot_width=30, plot_depth=45, floors=1, bedrooms=2,
                                parking_cars=1, balconies=1, extras=["utility"])),
    ("4BHK G+2 on 40x60", dict(plot_width=40, plot_depth=60, floors=3, bedrooms=4,
                               parking_cars=2, balconies=3, setback_front=3.0,
                               setback_rear=1.5, extras=["pooja", "study", "store"])),
    ("no parking, no balcony", dict(plot_width=25, plot_depth=40, floors=2, bedrooms=2,
                                    parking_cars=0, balconies=0, extras=[])),
    ("over-programmed brief", dict(plot_width=20, plot_depth=25, floors=1, bedrooms=6,
                                   parking_cars=2, balconies=2, extras=["pooja", "study"])),
]


def test_plans():
    section("Full plan generation")
    for name, kw in CASES:
        p = generate_plan(dict(units="ft", restarts=220, **kw))
        check(f"[{name}] returns a plan", p["ok"])

        plot = p["plot"]
        env = p["envelope"]
        rooms = p["rooms"]

        # --- the invariant everything else rests on ---------------------
        for lvl in range(p["requirements"]["floors"]):
            level_rooms = [r for r in rooms if r["floor"] == lvl
                           and not (r["type"] == "balcony" and not _inside(r, env))
                           and r["id"] != "parking_open"]
            rects = [Rect(r["x"], r["y"], r["w"], r["h"]) for r in level_rooms]
            overlaps = rects_overlap(rects, tol=0.01)
            check(f"[{name}] L{lvl} no overlapping spaces", not overlaps,
                  f"{len(overlaps)} overlapping pairs")
            covered = sum(r.area for r in rects)
            check(f"[{name}] L{lvl} tiles the envelope",
                  abs(covered - env["w"] * env["h"]) < 0.3,
                  f"covered {covered:.3f} vs {env['w'] * env['h']:.3f}")

        # --- containment -------------------------------------------------
        stray = [r["label"] for r in rooms
                 if r["type"] not in ("balcony", "parking") and not _inside(r, env)]
        check(f"[{name}] all enclosed spaces sit inside the setback line", not stray,
              str(stray))

        outside_plot = [r["label"] for r in rooms
                        if r["x"] < -0.05 or r["y"] < -0.05
                        or r["x"] + r["w"] > plot["w"] + 0.05
                        or r["y"] + r["h"] > plot["h"] + 0.05]
        check(f"[{name}] nothing spills off the plot", not outside_plot, str(outside_plot))

        # --- stair stacking ----------------------------------------------
        stairs = [r for r in rooms if r["type"] == "staircase"]
        if len(stairs) > 1:
            base = stairs[0]
            aligned = all(abs(s["x"] - base["x"]) < 0.05 and abs(s["y"] - base["y"]) < 0.05
                          for s in stairs)
            check(f"[{name}] stair core stacks on every level", aligned)

        # --- programme fidelity -------------------------------------------
        beds = [r for r in rooms if r["type"] in ("bedroom", "master_bedroom", "guest_bedroom")]
        check(f"[{name}] bedroom count matches the brief",
              len(beds) == p["requirements"]["bedrooms"],
              f"{len(beds)} vs {p['requirements']['bedrooms']}")

        # --- derived data is present and self-consistent --------------------
        m = p["metrics"]
        check(f"[{name}] carpet area is below built-up",
              0 < m["carpet_area"] <= m["builtup_area"] + 0.01)
        check(f"[{name}] cost is positive", p["cost"]["grand_total"] > 0)
        items = sum(i["amount"] for i in p["cost"]["items"])
        check(f"[{name}] cost line items sum to the direct total",
              abs(items - p["cost"]["direct_total"]) < 1.0)
        check(f"[{name}] validation ran", p["validation"]["checks_run"] > 10)
        check(f"[{name}] score is in range", 0 <= p["score"]["total"] <= 100)


def _inside(r, env, tol=0.05):
    return (r["x"] >= env["x"] - tol and r["y"] >= env["y"] - tol
            and r["x"] + r["w"] <= env["x"] + env["w"] + tol
            and r["y"] + r["h"] <= env["y"] + env["h"] + tol)


def test_determinism():
    section("Determinism")
    kw = dict(units="ft", plot_width=30, plot_depth=40, floors=2, bedrooms=3,
              parking_cars=1, balconies=1, extras=["pooja"], restarts=180)
    a = generate_plan(dict(kw))
    b = generate_plan(dict(kw))
    check("same brief gives the same seed", a["score"]["seed"] == b["score"]["seed"])
    check("same brief gives identical room geometry",
          [(r["id"], r["x"], r["y"], r["w"], r["h"]) for r in a["rooms"]]
          == [(r["id"], r["x"], r["y"], r["w"], r["h"]) for r in b["rooms"]])


def test_infeasible_is_reported():
    section("Infeasible briefs fail loudly")
    p = generate_plan(dict(units="ft", plot_width=18, plot_depth=22, floors=1,
                           bedrooms=5, parking_cars=2, restarts=120,
                           extras=["pooja", "study", "store"]))
    check("still returns a plan rather than crashing", p["ok"])
    check("reports errors instead of pretending it is fine",
          p["validation"]["counts"]["error"] > 0)
    check("marked non-compliant", p["validation"]["compliant"] is False)
    has_fix = any(f.get("fix") for f in p["validation"]["findings"])
    check("offers at least one actionable fix", has_fix)


if __name__ == "__main__":
    test_geometry()
    test_programme()
    test_brief_parser()
    test_normalise()
    test_plans()
    test_determinism()
    test_infeasible_is_reported()

    print(f"\n{'=' * 60}")
    if FAILED:
        print(f"{PASSED} passed, {len(FAILED)} FAILED")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print(f"All {PASSED} checks passed.")
