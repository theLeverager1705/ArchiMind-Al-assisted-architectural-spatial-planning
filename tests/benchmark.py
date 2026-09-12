"""
Layout-quality benchmark.

Runs a spread of realistic briefs and reports the aggregate error count, the
mean layout score and the slowest solve. Used to check that a change to the
solver is an actual improvement rather than a trade that helps one brief and
hurts three others.

    python tests/benchmark.py
"""

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.planner import FT_TO_M, generate_plan  # noqa: E402
from app.engine.validate import min_setbacks_for          # noqa: E402


def with_legal_setbacks(kw):
    """
    Apply the development-control minimum for the brief's frontage unless the
    brief already states one. The benchmark is meant to measure layout quality,
    so it must not be polluted by setback findings caused by its own inputs.
    """
    out = dict(kw)
    rule = min_setbacks_for(out["plot_width"] * FT_TO_M)
    out.setdefault("setback_front", rule["front"])
    out.setdefault("setback_rear", rule["rear"])
    out.setdefault("setback_left", rule["side"])
    out.setdefault("setback_right", rule["side"])
    return out

# Briefs a real client would bring, all with compliant setbacks for their
# frontage so the benchmark measures layout quality rather than bye-law input.
BRIEFS = [
    ("2BHK  25x40 single", dict(plot_width=25, plot_depth=40, floors=1, bedrooms=2,
                                parking_cars=1, balconies=1, extras=["utility"])),
    ("2BHK  30x40 G+1", dict(plot_width=30, plot_depth=40, floors=2, bedrooms=2,
                             parking_cars=1, balconies=1, extras=["utility", "store"])),
    ("3BHK  30x40 G+1", dict(plot_width=30, plot_depth=40, floors=2, bedrooms=3,
                             parking_cars=1, balconies=2, extras=["pooja", "utility"])),
    ("3BHK  30x50 G+1", dict(plot_width=30, plot_depth=50, floors=2, bedrooms=3,
                             parking_cars=1, balconies=2, extras=["pooja", "utility", "store"])),
    ("3BHK  35x50 G+1", dict(plot_width=35, plot_depth=50, floors=2, bedrooms=3,
                             parking_cars=2, balconies=2, extras=["pooja", "utility", "study"])),
    ("4BHK  40x60 G+2", dict(plot_width=40, plot_depth=60, floors=3, bedrooms=4,
                             parking_cars=2, balconies=3, setback_front=4.5,
                             setback_rear=3.0, setback_left=1.5, setback_right=1.5,
                             extras=["pooja", "study", "store", "utility"])),
    ("4BHK  40x60 G+1", dict(plot_width=40, plot_depth=60, floors=2, bedrooms=4,
                             parking_cars=2, balconies=2, setback_front=4.5,
                             setback_rear=3.0, setback_left=1.5, setback_right=1.5,
                             extras=["pooja", "utility"])),
    ("1BHK  20x30 G+1", dict(plot_width=20, plot_depth=30, floors=2, bedrooms=1,
                             parking_cars=1, balconies=1, extras=[])),
    ("3BHK  no parking", dict(plot_width=25, plot_depth=45, floors=2, bedrooms=3,
                              parking_cars=0, balconies=2, extras=["pooja", "utility"])),
    ("5BHK  50x80 G+2", dict(plot_width=50, plot_depth=80, floors=3, bedrooms=5,
                             parking_cars=3, balconies=4, setback_front=6.0,
                             setback_rear=3.0, setback_left=2.0, setback_right=2.0,
                             extras=["pooja", "study", "store", "utility", "guest_bedroom"])),
    ("3BHK  ground bed", dict(plot_width=35, plot_depth=45, floors=2, bedrooms=3,
                              parking_cars=1, balconies=2, ground_bedroom=True,
                              extras=["pooja", "utility"])),
    ("2BHK  open parking", dict(plot_width=30, plot_depth=50, floors=2, bedrooms=2,
                                parking_cars=1, parking_type="open", setback_front=5.5,
                                balconies=1, extras=["utility"])),
]


def run(restarts=500, show_detail=True):
    rows = []
    categories = Counter()
    titles = Counter()
    t_all = time.perf_counter()

    for name, kw in BRIEFS:
        t0 = time.perf_counter()
        p = generate_plan(dict(units="ft", restarts=restarts, **with_legal_setbacks(kw)))
        dt = (time.perf_counter() - t0) * 1000
        v = p["validation"]
        errs = [f for f in v["findings"] if f["severity"] == "error"]
        for f in errs:
            categories[f["category"]] += 1
            titles[f["title"]] += 1
        # A brief that cannot physically fit is supposed to fail. Separating
        # those out is what makes the remaining count a measure of the solver.
        infeasible = any(f["code"] == "PROG-deficit" for f in errs)
        rows.append((name, p["score"]["total"], v["counts"]["error"],
                     v["counts"]["warning"], dt, errs, infeasible))

    print(f"{'brief':<20} {'score':>6} {'err':>4} {'warn':>5} {'ms':>7}")
    print("-" * 48)
    for name, score, e, w, dt, errs, infeasible in rows:
        if e == 0:
            flag = ""
        elif infeasible:
            flag = "   (brief does not fit)"
        else:
            flag = "   <"
        print(f"{name:<20} {score:6.1f} {e:4d} {w:5d} {dt:7.0f}{flag}")
        if show_detail:
            for f in errs:
                print(f"{'':>22}- {f['title']}")

    n = len(rows)
    total_err = sum(r[2] for r in rows)
    total_warn = sum(r[3] for r in rows)
    clean = sum(1 for r in rows if r[2] == 0)
    feasible = [r for r in rows if not r[6]]
    feasible_clean = sum(1 for r in feasible if r[2] == 0)
    feasible_err = sum(r[2] for r in feasible)
    print("-" * 48)
    print(f"briefs          {n}")
    print(f"clean (0 err)   {clean}/{n}")
    print(f"total errors    {total_err}")
    print(f"feasible briefs {len(feasible)}  clean {feasible_clean}  errors {feasible_err}")
    print(f"total warnings  {total_warn}")
    print(f"mean score      {sum(r[1] for r in rows) / n:.2f}")
    print(f"min score       {min(r[1] for r in rows):.1f}")
    print(f"slowest         {max(r[4] for r in rows):.0f} ms")
    print(f"wall clock      {(time.perf_counter() - t_all):.1f} s")
    if categories:
        print("\nerrors by category:")
        for c, k in categories.most_common():
            print(f"  {k:3d}  {c}")
        print("\nmost common:")
        for t, k in titles.most_common(6):
            print(f"  {k:3d}  {t}")
    return total_err, sum(r[1] for r in rows) / n


if __name__ == "__main__":
    restarts = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    run(restarts)
