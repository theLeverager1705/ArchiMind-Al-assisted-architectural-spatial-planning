"""
ArchiMind API.

Thin HTTP layer: every endpoint validates its input, calls one engine function
and returns JSON. No planning logic lives here, which is what makes the engine
independently testable and the AI path swappable.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.brief import critique, interpret, parse_brief
from .ai.client import provider_status
from .engine.planner import generate_plan, normalise
from .engine.standards import (
    ADJACENCY_RULES, COST_ITEMS, COST_PERCENT_ITEMS, SPACE_STANDARDS,
)
from .engine.validate import min_setbacks_for

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(
    title="ArchiMind",
    description="AI-assisted architectural and spatial planning system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class PlanRequest(BaseModel):
    units: str = "ft"
    plot_width: float = 30
    plot_depth: float = 40
    setback_front: float = 1.5
    setback_rear: float = 1.0
    setback_left: float = 0.9
    setback_right: float = 0.9
    floors: int = 2
    bedrooms: int = 3
    bathrooms: int = 0
    parking_cars: int = 1
    parking_type: str = "covered"
    balconies: int = 1
    roof_type: str = "terrace"
    extras: list[str] = Field(default_factory=list)
    ground_bedroom: bool = False
    has_living: bool = True
    has_dining: bool = True
    facing: str = "N"
    quality: str = "standard"
    city_tier: str = "tier2"
    max_far: float = 2.0
    max_coverage: float = 0.65
    restarts: int = 260
    notes: str = ""
    rate_overrides: dict[str, float] = Field(default_factory=dict)


class BriefRequest(BaseModel):
    text: str = ""


class CritiqueRequest(BaseModel):
    plan: dict


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "ArchiMind",
        "version": app.version,
        "ai": provider_status(),
    }


@app.get("/api/standards")
def standards() -> dict:
    """
    The design rules the engine applies.

    Exposed so the UI can show what a check was measured against, and so the
    numbers in the app are auditable rather than hidden in the code.
    """
    return {
        "spaces": [
            {"type": k, "label": v["label"], "min_area": v["min_area"],
             "min_dim": v["min_dim"], "ideal_area": v["ideal_area"],
             "aspect_max": v["aspect_max"], "zone": v["zone"],
             "habitable": v["habitable"], "wet": v["wet"], "color": v["color"]}
            for k, v in SPACE_STANDARDS.items()
        ],
        "adjacency": ADJACENCY_RULES,
        "cost_items": COST_ITEMS,
        "cost_addons": COST_PERCENT_ITEMS,
    }


@app.get("/api/setback-rule")
def setback_rule(plot_width: float = 9.14) -> dict:
    """Minimum setbacks for a given frontage, so the UI can prefill legal values."""
    rule = min_setbacks_for(plot_width)
    return {"plot_width": plot_width, "minimum": rule}


@app.post("/api/plan")
def plan(req: PlanRequest) -> JSONResponse:
    """Generate a validated plan. This is the core endpoint."""
    try:
        result = generate_plan(req.model_dump())
        return JSONResponse(result)
    except Exception as exc:                      # never return an opaque 500 to the UI
        return JSONResponse(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}",
             "hint": "The requirements could not be planned. Try relaxing the brief."},
            status_code=422,
        )


@app.post("/api/interpret")
def interpret_brief(req: BriefRequest) -> JSONResponse:
    """
    Natural-language brief -> structured requirements.

    One AI call per submission; everything downstream is local. Falls back to a
    deterministic parser when no provider is configured.
    """
    try:
        return JSONResponse(interpret(req.text))
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}",
             "requirements": normalise(parse_brief(req.text or "")),
             "source": "rules", "understood": []},
            status_code=200,
        )


@app.post("/api/critique")
def critique_plan(req: CritiqueRequest) -> JSONResponse:
    """Architect-style review of a generated plan."""
    try:
        return JSONResponse(critique(req.plan))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                            status_code=422)


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
if WEB_DIR.exists():
    app.mount("/css", StaticFiles(directory=WEB_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=WEB_DIR / "js"), name="js")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app",
                host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")),
                reload=bool(os.environ.get("RELOAD")))


if __name__ == "__main__":
    run()
