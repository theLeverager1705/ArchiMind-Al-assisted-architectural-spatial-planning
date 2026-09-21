# ArchiMind — AI-Powered Architectural & Spatial Planning System

**Hackathon 2026 · Challenge 01**

Plot and requirements in → a **validated 2D floor plan**, a **consistent 3D model**, a
**spatial validation report** and a **transparent cost estimate** out.

```
Requirements ─▶ AI interpretation ─▶ Programme synthesis ─▶ Spatial solver
                                                                  │
        Cost ◀── Validation ◀── Topology (doors, windows, walls) ◀─┘
                     │
                     └─▶ 2D SVG plan  +  3D model   (one dataset, two renderings)
```

---

## 1. Quick start

```bash
cd archimind
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

Open <archimind-al-assisted-architectural.onrender.com> . It works immediately with **no API key** — the brief
parser and design reviewer fall back to deterministic local implementations.

To enable the LLM path, set one variable before starting:

```bash
export GEMINI_API_KEY=your_key      # or OPENAI_API_KEY
```

Run the tests and the layout benchmark:

```bash
python tests/test_engine.py         # 108 correctness checks
python tests/benchmark.py           # 12 realistic briefs, layout quality
```

---

## 2. The core idea

Most attempts at this problem ask an LLM to emit room rectangles. That produces
plans that overlap, leave gaps, and cannot be validated or costed.

**ArchiMind splits the problem by what each tool is actually good at:**

| Concern | Handled by | Why |
|---|---|---|
| Understanding an English brief | LLM | Language is what it is good at |
| Deciding what goes on which floor | Rule-based programme synthesis | Deterministic, auditable |
| Where every wall goes | Geometric solver | Must be exact, not plausible |
| Whether the plan is legal and usable | Validation engine | Must be checkable |
| What it costs | Quantity-driven cost model | Must be explainable |
| Reviewing the result in prose | LLM | Language again |

The LLM never produces geometry and never does arithmetic. Its output is merged
over a rule-based parse and pushed through the same `normalise()` clamp as manual
input, so an out-of-range or hallucinated value can never reach the solver.
**One AI call per submission** — everything else is local, which keeps it inside
free-tier limits.

---

## 3. The spatial solver

`app/engine/layout.py` — an **adjacency-driven slicing tree searched by seeded
multi-restart**.

1. **Fixed cores are reserved first.** The parking bay hugs the street frontage
   (a car must be able to drive into it); the staircase is anchored inside what
   the parking leaves free, so the two can never collide. The stair keeps an
   **identical footprint on every level**, so the flights actually stack — a check
   most generated plans quietly fail.

2. **Spaces are ordered into a chain by affinity seriation.** Consecutive entries
   are the ones that want to touch, because a slicing tree keeps sequence
   neighbours geometrically close.

3. **The chain is cut with guillotine splits.** Several cut points and both axes
   are scored at each step and the best is taken. Because a slicing tree
   *partitions*, the floor is always filled with **no gaps and no overlaps** — this
   is what makes areas, the wall network and the 3D extrusion exact rather than
   approximate.

4. **Repair passes** fix what the partition could not:
   - `repair_swaps` trades rectangles between rooms when both fit better,
     weighted by local affinity so it cannot buy proportion by separating the
     kitchen from the dining room;
   - `repair_dimensions` nudges a shared wall to widen an undersized room, taking
     the space from neighbours that can spare it;
   - `repair_relationships` hill-climbs room-to-rectangle assignment to recover
     broken adjacencies — it only *exchanges* rectangles, so the floor stays
     exactly tiled no matter what the search does.

5. **~500 candidates are scored and the best wins**, on eight weighted criteria:

   | Criterion | Weight | Meaning |
   |---|---|---|
   | Relationships | 26% | Required and preferred adjacencies met |
   | Feasibility | 24% | Every room meets minimum area and clear width |
   | Entrance | 10% | The front door reaches the street frontage |
   | Proportion | 10% | Rooms stay within a workable aspect ratio |
   | Area fit | 10% | Delivered area matches the programme budget |
   | Daylight | 12% | Habitable rooms reach an external wall |
   | Privacy | 5% | Bedrooms do not open off the entrance or parking |
   | Circulation | 3% | Every space is reachable through a door |

   Feasibility blends the **mean with the worst room** — a plan with one unusable
   space is not 94% feasible, and averaging alone would let the solver ship
   exactly that. It also charges for rooms that come out *over* their maximum:
   without that, the repair passes will park a 2 m² powder room in the best 11 m²
   rectangle on the floor to win an adjacency, and leave the living room in the
   strip that's left.

The search is **deterministic**: the same brief always gives the same plan, so
nudging one slider does not scramble the layout.

---

## 4. Topology

`app/engine/topology.py` derives what turns a partition into a drawing:

- **Contacts** — every pair of spaces sharing usable wall length.
- **Doors** — required relationships first, then preferred ones, then a spanning
  tree over the contact graph so **every space is reachable from the entrance**.
  A door is never cut through a forbidden adjacency (kitchen↔bathroom).
- **Windows** — sized from the NBC light-and-ventilation rule (openings ≥ 1/10 of
  floor area), spread across available external walls and slid clear of doors.
- **Walls** — room boundaries are collected per grid line and the intervals
  merged, giving exactly one wall run per physical wall. This is what the 3D view
  extrudes; without it, every shared wall would be doubled.

Relationship rules live in `standards.py` with a weight, a required flag and a
**written rationale**, so every finding can explain itself:

> *Kitchen ↔ Dining — required — "Food must travel from kitchen to dining without
> crossing the living room."*

---

## 5. Validation

`app/engine/validate.py` runs **30+ checks** across eight categories and produces
structured findings — severity, the rule applied, the numbers that failed it, the
rooms involved, and often a **one-click fix**:

- **Setbacks** against development-control minimums banded by plot frontage
- **Ground coverage** banded by plot area (small plots are permitted to cover
  more of the site — a flat 65% flags compliant 30×40 ft houses as illegal) and
  **FAR** against the permitted limit
- **Geometry integrity** — overlaps, gaps, anything breaching the setback line
- **Room sizes** — minimum area, minimum clear width, aspect ratio, and whether a
  standard bed layout physically fits
- **Relationships** — required, preferred and forbidden adjacencies
- **Circulation** — reachability per floor, stair stacking, stair size, main entrance
- **Light & ventilation** — external wall access and glazing ratio per room
- **Services** — parking bay dimensions, bathroom provision, and **wet-stack
  alignment** (upper-floor bathrooms sitting over wet rooms below)

An infeasible brief is reported as an **area deficit with the exact shortfall**,
not silently squeezed into unusable rectangles.

---

## 6. Rendering

Both views are generated from **the same room rectangles, wall runs and
openings**. They are not two models; they are two renderings of one dataset,
which is why they cannot drift apart.

**2D** (`web/js/plan2d.js`) — SVG drawn in real metres: wall poché at true
thickness, doors knocked out of the wall with swing arcs, windows with frame and
glazing lines, furniture symbols (beds with pillow bands, L-shaped kitchen
counters with sink and hob, sanitary fittings, dining tables with chairs, stair
treads with a direction arrow, cars), room labels with area and dimensions,
dimension chains on two sides, a north arrow oriented to the brief, and a scale
bar. Pan, zoom, hover-to-inspect, click-to-highlight, SVG export.

**3D** (`web/js/view3d.js`) — Three.js. Walls are **split around their openings**
and capped with lintels and sills, so windows are real holes with glazing, not
painted rectangles. Floor slabs, cantilevered and recessed balconies with
railings, dog-legged stair flights, cars, flat/terrace/sloped roofs with a stair
head room. Explode-floors, cutaway walls, per-level isolation. Orbit control is
implemented in-file so the page depends on exactly one external script.

---

## 7. Cost

`app/engine/cost.py` — no lump-sum rate per square foot. **Eleven line items**,
each driven by a quantity actually measured from the plan:

| Driver | Measured from |
|---|---|
| Wall area | the extracted wall network × 2 faces × ceiling height |
| Opening count | the real doors and windows placed |
| Wet points | rooms flagged as needing plumbing |
| Built-up | weighted — parking 42%, balcony 55%, terrace 30% of an enclosed m² |

Plus four percentage add-ons (preliminaries, fees, contingency, GST), scaled by
specification level and city tier. Every row shows its formula and basis in the
UI, and the whole table recomputes when a slider moves. Output lands around
₹2,400/sq ft at standard specification in a Tier-2 city.

---

## 8. API

| Endpoint | Purpose |
|---|---|
| `POST /api/plan` | Requirements → complete validated plan |
| `POST /api/interpret` | English brief → structured requirements |
| `POST /api/critique` | Plan → architect-style design review |
| `GET /api/standards` | Every design rule and rate the engine applies |
| `GET /api/setback-rule` | Legal minimum setbacks for a given frontage |
| `GET /api/health` | Service and AI provider status |

```bash
curl -X POST localhost:8000/api/plan -H 'Content-Type: application/json' \
  -d '{"plot_width":30,"plot_depth":40,"floors":2,"bedrooms":3,"parking_cars":1}'
```

---

## 9. Layout

```
archimind/
├── app/
│   ├── main.py              FastAPI routes (thin — no planning logic)
│   ├── engine/
│   │   ├── standards.py     NBC-informed space standards, topology rules, rates
│   │   ├── geometry.py      Rectangle algebra, shared-wall detection
│   │   ├── program.py       Requirements → floor-by-floor space schedule
│   │   ├── layout.py        The solver: seriation, slicing, repair, scoring
│   │   ├── topology.py      Contacts, doors, windows, walls, reachability
│   │   ├── furniture.py     Fixture layout per room type
│   │   ├── metrics.py       Area accounting (single source of truth)
│   │   ├── validate.py      30+ checks → structured findings
│   │   ├── cost.py          Quantity-driven cost model
│   │   └── planner.py       The pipeline
│   └── ai/
│       ├── client.py        Gemini / OpenAI over plain HTTP
│       └── brief.py         Interpretation + review, both with local fallbacks
├── web/                     No build step — open and it runs
└── tests/
    ├── test_engine.py       108 correctness checks
    └── benchmark.py         12 briefs, layout-quality regression guard
```

## 10. Measured quality

`tests/benchmark.py` runs twelve realistic briefs — 1BHK to 5BHK, single storey
to G+2, covered and open parking, with and without a ground-floor bedroom — and
reports aggregate errors, mean score and the slowest solve. It exists so that a
change to the solver can be shown to be an improvement rather than a trade that
helps one brief and hurts three others.

Two of the twelve briefs are deliberately impossible (a 1BHK plus a car on a
20×30 ft plot); those are *supposed* to fail, and the benchmark separates them so
the remaining count measures the solver rather than the brief.

Tuning against it during development moved the suite from **45 errors to 30**
(16 across the ten feasible briefs), at a mean layout score of 84 and a worst-case
solve of 2.9 s for a G+2. Three findings it produced were real bugs, not tuning
opportunities:

- the repair pass was trading daylight away — it could fix an adjacency by
  swapping a bedroom into the middle of the plan, turning a warning into a worse
  error. Daylight is now part of the repair objective.
- open parking in the front setback was being reported as a space breaching the
  setback line and as unreachable. Both were false positives; it is now excluded
  from the floor-plate and circulation checks by design.
- a perimeter-aware split penalty *looked* obviously correct and made the suite
  worse (30 → 35). It was reverted. This is exactly what the benchmark is for.

## 11. What the tests guarantee

Beyond unit coverage of geometry, the programme and the brief parser, the suite
asserts the invariants the whole system rests on, across five briefs:

- every floor **tiles its envelope exactly** — no overlaps, no gaps
- no enclosed space crosses the setback line or leaves the plot
- the **stair core stacks** on every level
- the bedroom count matches the brief
- carpet ≤ built-up, and the cost line items sum to the stated total
- the same brief is **reproducible** down to identical room geometry
- an impossible brief **reports errors and offers a fix** instead of pretending
