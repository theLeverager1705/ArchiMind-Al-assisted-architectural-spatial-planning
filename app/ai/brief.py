"""
AI brief interpretation and design review.

Two jobs, both language jobs:

  interpret()  English brief -> structured requirements
  critique()   finished plan  -> a short architect-style review

Both have a deterministic fallback that runs when no API key is configured or the
call fails, so a demo never dies on a network error. The fallback for
interpret() is a real rule-based parser, not a stub: it handles the phrasing an
Indian client actually uses ("30x40 site", "3BHK", "G+1", "car parking",
"pooja room", "east facing").
"""

from __future__ import annotations

import re

from ..engine.planner import VALID_EXTRAS, normalise
from .client import AIError, complete, parse_json, provider_status

SYSTEM = """You are an architectural intake assistant for a residential planning system in India.
Convert the client's brief into a JSON requirement object. Output JSON only.

Schema (use exactly these keys; omit a key if the brief does not mention it):
  units            "ft" or "m"        -- units of plot_width/plot_depth only
  plot_width       number             -- street frontage
  plot_depth       number             -- depth into the plot
  setback_front    number, METRES
  setback_rear     number, METRES
  setback_left     number, METRES
  setback_right    number, METRES
  floors           integer 1-4        -- "G+1" means 2 floors, "G+2" means 3
  bedrooms         integer 0-8        -- "3BHK" means 3 bedrooms
  bathrooms        integer 0-8        -- 0 means let the system decide
  parking_cars     integer 0-4
  parking_type     "covered" or "open"
  balconies        integer 0-6
  roof_type        "flat", "terrace" or "sloped"
  ground_bedroom   boolean            -- a bedroom required on the ground floor
  facing           "N", "E", "S" or "W"
  extras           array from: pooja, study, home_office, store, utility, guest_bedroom
  quality          "economy", "standard", "premium" or "luxury"
  notes            string             -- anything else worth recording

Rules:
- Indian plot sizes are quoted in feet ("30x40", "40 by 60"). Assume feet unless the brief says metres.
- Do not invent values the brief does not imply. Omit instead.
- Return only the JSON object."""


def interpret(text: str) -> dict:
    """
    English brief -> normalised requirements.

    The model's output is merged over the rule-based parse and then pushed
    through the engine's own normalise(), so out-of-range or nonsense values are
    clamped before they can reach the solver. That is deliberate: the brief says
    AI output should not be blindly trusted.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty brief", "requirements": normalise({}),
                "source": "none", "understood": []}

    rule_based = parse_brief(text)
    status = provider_status()
    source = "rules"
    ai_raw: dict = {}
    warning = ""

    if status["available"]:
        try:
            ai_raw = parse_json(complete(SYSTEM, text, json_mode=True, max_tokens=700))
            if ai_raw:
                source = f"{status['provider']}:{status['model']}"
        except (AIError, Exception) as exc:   # network, quota, malformed - all recoverable
            warning = f"AI call failed ({type(exc).__name__}); used the rule-based parser."

    merged = dict(rule_based)
    for k, v in (ai_raw or {}).items():
        if v is not None and v != "" and v != []:
            merged[k] = v

    if isinstance(merged.get("extras"), list):
        merged["extras"] = [e for e in merged["extras"] if e in VALID_EXTRAS]

    req = normalise(merged)
    return {
        "ok": True,
        "requirements": req,
        "source": source,
        "ai_raw": ai_raw,
        "rule_based": rule_based,
        "understood": describe(req),
        "warning": warning,
    }


# --------------------------------------------------------------------------
# Deterministic parser (also the fallback)
# --------------------------------------------------------------------------
WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "single": 1, "double": 2, "triple": 3,
}

EXTRA_PATTERNS = {
    "pooja": r"\b(pooja|puja|prayer|mandir)\b",
    "study": r"\bstudy\b",
    "home_office": r"\b(home\s*office|work\s*from\s*home|wfh)\b",
    "store": r"\b(store|storage|store\s*room)\b",
    "utility": r"\b(utility|wash\s*area|laundry)\b",
    "guest_bedroom": r"\bguest\s*(bed)?room\b",
}


def _int_near(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text)
    if not m:
        return None
    for g in m.groups():
        if not g:
            continue
        g = g.strip().lower()
        if g.isdigit():
            return int(g)
        if g in WORD_NUM:
            return WORD_NUM[g]
    return None


def parse_brief(text: str) -> dict:
    """Rule-based extraction. Deterministic, offline, and good enough to demo on."""
    t = " " + text.lower().strip() + " "
    out: dict = {}

    # Plot size: "30x40", "30 x 40 ft", "40 by 60 feet", "9 x 12 m"
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:x|by|\*|×)\s*(\d{1,3}(?:\.\d+)?)\s*"
                  r"(ft|feet|foot|m|meter|metre|metres|meters)?", t)
    if m:
        w, d, unit = float(m.group(1)), float(m.group(2)), (m.group(3) or "")
        metric = unit.startswith("m") and not unit.startswith("min")
        # A bare "9 x 12" is metres only if it is far too small to be feet.
        if not unit and max(w, d) <= 25:
            metric = True
        out["units"] = "m" if metric else "ft"
        out["plot_width"], out["plot_depth"] = w, d

    # Bedrooms: "3BHK", "3 bhk", "three bedrooms", "2 bed"
    bhk = re.search(r"\b(\d)\s*bhk\b", t)
    if bhk:
        out["bedrooms"] = int(bhk.group(1))
    else:
        n = _int_near(t, r"\b(\d|one|two|three|four|five|six)\s*(?:bed\s*rooms?|bedrooms?|beds?)\b")
        if n is not None:
            out["bedrooms"] = n

    n = _int_near(t, r"\b(\d|one|two|three|four)\s*(?:bath\s*rooms?|bathrooms?|baths?|toilets?)\b")
    if n is not None:
        out["bathrooms"] = n

    # Floors: "G+1", "ground plus two", "two floors", "duplex", "single storey"
    gp = re.search(r"\bg\s*\+\s*(\d)\b", t)
    if gp:
        out["floors"] = int(gp.group(1)) + 1
    elif re.search(r"\bground\s*(?:floor)?\s*(?:\+|plus)\s*(one|two|three|\d)\b", t):
        n = _int_near(t, r"\bground\s*(?:floor)?\s*(?:\+|plus)\s*(one|two|three|\d)\b")
        if n:
            out["floors"] = n + 1
    elif re.search(r"\b(single|one)[\s-]*(storey|story|floor|floored)\b|\bground floor only\b", t):
        out["floors"] = 1
    elif re.search(r"\bduplex\b", t):
        out["floors"] = 2
    elif re.search(r"\btriplex\b", t):
        out["floors"] = 3
    else:
        n = _int_near(t, r"\b(\d|one|two|three|four)\s*(?:floors?|storeys?|stories?|levels?)\b")
        if n is not None:
            out["floors"] = n

    # Parking
    if re.search(r"\bno\s*(?:car\s*)?park", t):
        out["parking_cars"] = 0
    else:
        n = _int_near(t, r"\b(\d|one|two|three|single|double)\s*(?:car|vehicle)s?\b")
        if n is not None:
            out["parking_cars"] = n
        elif re.search(r"\b(car\s*park|parking|garage|porch|carport)\b", t):
            out["parking_cars"] = 1
    if re.search(r"\b(covered|stilt|basement)\s*park|garage\b", t):
        out["parking_type"] = "covered"
    elif re.search(r"\b(open|uncovered)\s*park|car\s*porch\b", t):
        out["parking_type"] = "open"

    # Balconies
    n = _int_near(t, r"\b(\d|one|two|three|four)\s*balcon(?:y|ies)\b")
    if n is not None:
        out["balconies"] = n
    elif re.search(r"\bbalcon(?:y|ies)\b", t):
        out["balconies"] = 1
    elif re.search(r"\bno\s*balcon", t):
        out["balconies"] = 0

    # Roof
    if re.search(r"\b(sloping|sloped|pitched|gable|tiled)\s*roof\b", t):
        out["roof_type"] = "sloped"
    elif re.search(r"\b(terrace|open\s*terrace|roof\s*garden)\b", t):
        out["roof_type"] = "terrace"
    elif re.search(r"\bflat\s*roof\b", t):
        out["roof_type"] = "flat"

    # Facing
    f = re.search(r"\b(north|south|east|west)[\s-]*facing\b", t)
    if f:
        out["facing"] = f.group(1)[0].upper()

    # Setbacks: "3m front setback", "setback 1.5"
    for side in ("front", "rear", "left", "right"):
        sm = re.search(rf"(\d+(?:\.\d+)?)\s*m?\s*(?:metre|meter)?s?\s*{side}\s*set\s*back", t) \
            or re.search(rf"{side}\s*set\s*back\s*(?:of\s*)?(\d+(?:\.\d+)?)", t)
        if sm:
            out[f"setback_{side}"] = float(sm.group(1))

    # Extras
    extras = [key for key, pat in EXTRA_PATTERNS.items() if re.search(pat, t)]
    if extras:
        out["extras"] = extras

    if re.search(r"\b(bed\s*room|bedroom)\s*(?:on|at)\s*(?:the\s*)?ground\b|\belderly\b|"
                 r"\bparents?\s*(?:bed)?room\s*(?:on|at)\s*ground\b", t):
        out["ground_bedroom"] = True

    for q in ("economy", "standard", "premium", "luxury"):
        if re.search(rf"\b{q}\b", t):
            out["quality"] = q
            break
    if re.search(r"\bbudget\b|\baffordable\b|\blow\s*cost\b", t):
        out["quality"] = "economy"

    out["notes"] = text.strip()[:2000]
    return out


def describe(req: dict) -> list[str]:
    """Plain-English echo of what was understood, shown back for confirmation."""
    unit = req["units"]
    bits = [
        f"Plot {req['plot_width_input']:g} x {req['plot_depth_input']:g} {unit} "
        f"({req['plot_width']:.2f} x {req['plot_depth']:.2f} m)",
        f"{req['floors']} floor{'s' if req['floors'] > 1 else ''} "
        f"(G+{req['floors'] - 1})" if req["floors"] > 1 else "Single storey",
        f"{req['bedrooms']} bedroom{'s' if req['bedrooms'] != 1 else ''}",
    ]
    if req["bathrooms"]:
        bits.append(f"{req['bathrooms']} bathrooms")
    else:
        bits.append("bathrooms sized automatically")
    if req["parking_cars"]:
        bits.append(f"{req['parking_cars']} {req['parking_type']} car space"
                    f"{'s' if req['parking_cars'] > 1 else ''}")
    else:
        bits.append("no parking")
    if req["balconies"]:
        bits.append(f"{req['balconies']} balcon{'ies' if req['balconies'] > 1 else 'y'}")
    if req["extras"]:
        bits.append("extras: " + ", ".join(e.replace("_", " ") for e in req["extras"]))
    bits.append(f"setbacks F{req['setback_front']:g} / R{req['setback_rear']:g} / "
                f"L{req['setback_left']:g} / R{req['setback_right']:g} m")
    bits.append(f"{req['roof_type']} roof, {req['facing']} facing, {req['quality']} finish")
    return bits


# --------------------------------------------------------------------------
# Design review
# --------------------------------------------------------------------------
CRITIQUE_SYSTEM = """You are a senior residential architect reviewing a generated floor plan in India.
You are given the measured plan data and the validation findings the engine already computed.

Write a short review in this exact structure, using plain text with no markdown headings:
VERDICT: one sentence on whether this plan is worth developing.
STRENGTHS: two or three bullet lines starting with "- ".
CONCERNS: two or three bullet lines starting with "- ", each naming the specific room or metric.
NEXT: two bullet lines starting with "- " suggesting a concrete change to the brief.

Rules:
- Be specific and quantitative; cite the actual room names and numbers given to you.
- Do not invent rooms, dimensions or problems that are not in the data.
- Do not repeat the raw findings verbatim; interpret them for a client.
- Under 220 words."""


def critique(plan: dict) -> dict:
    """Architect-style review of a finished plan, with a deterministic fallback."""
    summary = _plan_summary(plan)
    status = provider_status()

    if status["available"]:
        try:
            text = complete(CRITIQUE_SYSTEM, summary, json_mode=False, max_tokens=600)
            if text and text.strip():
                return {"ok": True, "text": text.strip(),
                        "source": f"{status['provider']}:{status['model']}"}
        except Exception:
            pass   # fall through to the local reviewer

    return {"ok": True, "text": local_critique(plan), "source": "rule-based"}


def _plan_summary(plan: dict) -> str:
    m, v, s = plan["metrics"], plan["validation"], plan["score"]
    req = plan["requirements"]
    lines = [
        f"Brief: {req['bedrooms']}BHK over {req['floors']} floor(s) on a "
        f"{req['plot_width']:.2f} x {req['plot_depth']:.2f} m plot, "
        f"{req['parking_cars']} {req['parking_type']} car space(s).",
        f"Measured: built-up {m['builtup_area']:.1f} m2, carpet {m['carpet_area']:.1f} m2 "
        f"({m['efficiency'] * 100:.0f}% efficient), coverage {m['coverage'] * 100:.0f}%, "
        f"FAR {m['far']:.2f}.",
        f"Layout score {s['total']:.0f}/100: "
        + ", ".join(f"{k} {val:.0f}" for k, val in s["parts"].items()),
        f"Estimated cost Rs {plan['cost']['grand_total']:,.0f} "
        f"(Rs {plan['cost']['per_sqft']:,.0f}/sqft).",
        "",
        "Rooms:",
    ]
    for r in plan["rooms"]:
        lines.append(f"  L{r['floor']} {r['label']}: {r['w']:.2f} x {r['h']:.2f} m "
                     f"= {r['area']:.1f} m2")
    lines.append("")
    lines.append(f"Validation: {v['counts']['error']} errors, {v['counts']['warning']} warnings, "
                 f"{v['counts']['pass']} checks passed.")
    for f in v["findings"]:
        if f["severity"] in ("error", "warning"):
            lines.append(f"  [{f['severity']}] {f['title']}: {f['message']}")
    return "\n".join(lines)


def local_critique(plan: dict) -> str:
    """
    Deterministic review assembled from the engine's own findings.

    This is what the demo shows with no API key, and it is written from real
    measured data rather than generic filler.
    """
    m, v, s = plan["metrics"], plan["validation"], plan["score"]
    errs = [f for f in v["findings"] if f["severity"] == "error"]
    warns = [f for f in v["findings"] if f["severity"] == "warning"]
    parts = s["parts"]

    if not errs and s["total"] >= 80:
        verdict = (f"A sound scheme: {m['builtup_area']:.0f} m2 built-up at "
                   f"{m['efficiency'] * 100:.0f}% carpet efficiency with every regulatory "
                   f"and dimensional check passing.")
    elif not errs:
        verdict = (f"Workable but not yet resolved: all hard checks pass, though the layout "
                   f"scores only {s['total']:.0f}/100 and would benefit from a looser brief.")
    else:
        verdict = (f"Not yet buildable as drawn: {len(errs)} hard issue"
                   f"{'s' if len(errs) != 1 else ''} must be resolved first.")

    best = sorted(parts.items(), key=lambda kv: -kv[1])[:3]
    strengths = [f"- {k.replace('_', ' ').title()} scores {val:.0f}/100." for k, val in best]
    strengths.append(f"- Coverage {m['coverage'] * 100:.0f}% and FAR {m['far']:.2f} both sit "
                     f"inside the permitted envelope.")

    concerns = [f"- {f['title']}. {f['suggestion'] or f['message']}" for f in (errs + warns)[:3]]
    if not concerns:
        weakest = min(parts.items(), key=lambda kv: kv[1])
        concerns = [f"- {weakest[0].replace('_', ' ').title()} is the weakest dimension at "
                    f"{weakest[1]:.0f}/100; there is room to improve it."]

    nxt = []
    fixes = [f["fix"] for f in errs + warns if f.get("fix")]
    for fix in fixes[:2]:
        nxt.append(f"- {fix['label']}.")
    if len(nxt) < 2:
        nxt.append(f"- Compare an alternative with one more or one fewer floor; at "
                   f"{m['coverage'] * 100:.0f}% coverage there is headroom either way.")
    if len(nxt) < 2:
        nxt.append("- Try the open-parking option to free envelope area for the public zone.")

    return "\n".join([
        f"VERDICT: {verdict}", "",
        "STRENGTHS:", *strengths[:3], "",
        "CONCERNS:", *concerns[:3], "",
        "NEXT:", *nxt[:2],
    ])
