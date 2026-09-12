"""Developer smoke test: run the solver end to end and print what it produced."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.geometry import Rect, rects_overlap          # noqa: E402
from app.engine.layout import place_balconies, solve          # noqa: E402
from app.engine.program import build_programme                # noqa: E402
from app.engine.topology import (                             # noqa: E402
    build_contacts, extract_walls, place_doors, place_windows,
    reachability_report,
)

FT = 0.3048


def run(name, plot_w_ft, plot_d_ft, floors, bedrooms, cars, balconies, extras,
        setbacks=(1.5, 1.0, 0.9, 0.9)):
    pw, pd = plot_w_ft * FT, plot_d_ft * FT
    sf, sr, sl, srt = setbacks
    env = Rect(sl, sf, pw - sl - srt, pd - sf - sr).snapped()

    req = dict(floors=floors, bedrooms=bedrooms, bathrooms=0, parking_cars=cars,
               balconies=balconies, extras=extras, ground_bedroom=False,
               parking_type="covered",
               roof_type="terrace", envelope_area=env.area,
               has_living=True, has_dining=True)

    t0 = time.perf_counter()
    prog = build_programme(req)
    cand = solve(prog, env, restarts=260)
    bal, bal_notes = place_balconies(prog.balconies, cand.rooms, env,
                                     dict(front=sf, rear=sr, left=sl, right=srt))
    rooms = cand.rooms + bal
    contacts = build_contacts(cand.rooms)
    doors = place_doors(cand.rooms, contacts, env)
    windows = place_windows(cand.rooms, env, doors)
    walls = extract_walls(cand.rooms, env)
    reach = reachability_report(cand.rooms, doors)
    dt = (time.perf_counter() - t0) * 1000

    print("=" * 78)
    print(f"{name}   plot {plot_w_ft}x{plot_d_ft} ft   envelope "
          f"{env.w:.2f}x{env.h:.2f} m = {env.area:.1f} m2")
    print(f"  solved in {dt:6.0f} ms   score {cand.score * 100:5.1f}/100   seed {cand.seed}")
    print("  " + "  ".join(f"{k}={v:.2f}" for k, v in cand.breakdown["parts"].items()))
    print(f"  rooms {len(rooms)}  doors {len(doors)}  windows {len(windows)}  walls {len(walls)}")

    for lvl in sorted({r.floor for r in rooms}):
        fr = [r for r in rooms if r.floor == lvl]
        covered = sum(r.rect.area for r in fr)
        ov = rects_overlap([r.rect for r in fr])
        gap = env.area - covered
        flag = ""
        if ov:
            flag += f"  !! {len(ov)} OVERLAPS"
        if abs(gap) > 0.05:
            flag += f"  !! GAP {gap:.3f} m2"
        un = reach.get(lvl, {}).get("unreachable", [])
        if un:
            flag += f"  !! UNREACHABLE {un}"
        print(f"  -- level {lvl}: covered {covered:.2f}/{env.area:.2f} m2{flag}")
        for r in sorted(fr, key=lambda r: (r.rect.y, r.rect.x)):
            bad = []
            if r.rect.short_side < r.min_dim - 1e-3:
                bad.append(f"minDim {r.rect.short_side:.2f}<{r.min_dim}")
            if r.rect.aspect > r.aspect_max + 1e-3:
                bad.append(f"aspect {r.rect.aspect:.2f}>{r.aspect_max}")
            if r.rect.area < r.min_area - 1e-3:
                bad.append(f"area {r.rect.area:.1f}<{r.min_area}")
            print(f"       {r.label:<22} {r.rect.w:5.2f} x {r.rect.h:5.2f}"
                  f" = {r.rect.area:6.2f} m2   {'  '.join(bad)}")
    for n in bal_notes + prog.notes:
        print(f"  note: {n}")
    for d in prog.deficits:
        print(f"  DEFICIT: {d}")
    return cand


if __name__ == "__main__":
    run("3BHK G+1 duplex", 30, 40, 2, 3, 1, 2, ["pooja", "utility", "store"])
    run("2BHK single storey", 25, 35, 1, 2, 1, 1, ["utility"])
    run("4BHK G+2", 40, 60, 3, 4, 2, 3, ["pooja", "study", "utility", "store"])
    run("Tight 3BHK on small plot", 20, 30, 2, 3, 1, 1, ["utility"])
    run("Infeasible: 6BHK on tiny plot", 20, 25, 1, 6, 2, 2, ["pooja", "study"])
