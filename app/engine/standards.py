"""
Architectural design standards, space programme rules and adjacency preferences.

Values are informed by the National Building Code of India (NBC 2016) Part 3
(Development Control) and common Indian residential practice. They are kept in
one place so every downstream module (programme synthesis, layout, validation,
costing) reasons from a single source of truth, and so every validation message
can cite the exact rule it applied.

All dimensions are in metres, all areas in square metres.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Zones
# --------------------------------------------------------------------------
PUBLIC = "public"            # guests are expected here
PRIVATE = "private"          # bedrooms and their bathrooms
SERVICE = "service"          # kitchen, utility, stores
CIRCULATION = "circulation"  # foyer, corridor, staircase
OUTDOOR = "outdoor"          # balcony, terrace, parking, porch

ZONE_LABEL = {
    PUBLIC: "Public",
    PRIVATE: "Private",
    SERVICE: "Service",
    CIRCULATION: "Circulation",
    OUTDOOR: "Outdoor",
}

ZONE_COLOR = {
    PUBLIC: "#3b82f6",
    PRIVATE: "#ec4899",
    SERVICE: "#f59e0b",
    CIRCULATION: "#64748b",
    OUTDOOR: "#10b981",
}

# --------------------------------------------------------------------------
# Space standards
# --------------------------------------------------------------------------
# min_area   : hard minimum floor area (NBC-informed); below this -> error
# min_dim    : hard minimum clear width in either direction; below this -> error
# ideal_area : the area the programme aims for when space is available
# max_area   : cap so one room does not absorb the whole envelope
# aspect_max : worst acceptable long:short ratio; above this -> warning
# habitable  : NBC "habitable room" -> needs natural light and ventilation
# wet        : needs plumbing; drives cost and vertical-stacking checks
SPACE_STANDARDS: dict[str, dict] = {
    "foyer": dict(
        label="Foyer", min_area=2.0, min_dim=1.2, ideal_area=4.0, max_area=8.0,
        aspect_max=2.6, zone=CIRCULATION, habitable=False, wet=False,
        color="#e8eef7", priority=90,
    ),
    "living": dict(
        label="Living", min_area=11.0, min_dim=3.0, ideal_area=20.0, max_area=34.0,
        aspect_max=2.0, zone=PUBLIC, habitable=True, wet=False,
        color="#cfe3f7", priority=100,
    ),
    "dining": dict(
        label="Dining", min_area=7.5, min_dim=2.4, ideal_area=12.0, max_area=20.0,
        aspect_max=2.0, zone=PUBLIC, habitable=True, wet=False,
        color="#d6ecdc", priority=80,
    ),
    "kitchen": dict(
        label="Kitchen", min_area=5.5, min_dim=1.8, ideal_area=9.5, max_area=16.0,
        aspect_max=2.6, zone=SERVICE, habitable=True, wet=True,
        color="#fbe6cc", priority=95,
    ),
    "utility": dict(
        label="Utility", min_area=2.4, min_dim=1.2, ideal_area=4.0, max_area=7.0,
        aspect_max=3.0, zone=SERVICE, habitable=False, wet=True,
        color="#f2e8d5", priority=40,
    ),
    "store": dict(
        label="Store", min_area=1.8, min_dim=1.0, ideal_area=3.2, max_area=6.0,
        aspect_max=3.0, zone=SERVICE, habitable=False, wet=False,
        color="#eeeae0", priority=30,
    ),
    "pooja": dict(
        label="Pooja", min_area=1.5, min_dim=1.1, ideal_area=2.6, max_area=5.0,
        aspect_max=2.2, zone=PUBLIC, habitable=False, wet=False,
        color="#f7e9c9", priority=45,
    ),
    "study": dict(
        label="Study", min_area=5.0, min_dim=2.1, ideal_area=8.0, max_area=13.0,
        aspect_max=2.2, zone=PRIVATE, habitable=True, wet=False,
        color="#e3e0f4", priority=50,
    ),
    "home_office": dict(
        label="Home Office", min_area=5.5, min_dim=2.1, ideal_area=9.0, max_area=14.0,
        aspect_max=2.2, zone=PRIVATE, habitable=True, wet=False,
        color="#e3e0f4", priority=50,
    ),
    "master_bedroom": dict(
        label="Master Bedroom", min_area=11.0, min_dim=3.0, ideal_area=16.5, max_area=26.0,
        aspect_max=1.9, zone=PRIVATE, habitable=True, wet=False,
        color="#f6dfe4", priority=98,
    ),
    "bedroom": dict(
        label="Bedroom", min_area=8.5, min_dim=2.7, ideal_area=12.5, max_area=20.0,
        aspect_max=2.0, zone=PRIVATE, habitable=True, wet=False,
        color="#f7e5ea", priority=92,
    ),
    "guest_bedroom": dict(
        label="Guest Bedroom", min_area=8.5, min_dim=2.7, ideal_area=12.0, max_area=18.0,
        aspect_max=2.0, zone=PRIVATE, habitable=True, wet=False,
        color="#f7e8ec", priority=70,
    ),
    "bathroom": dict(
        label="Bathroom", min_area=2.8, min_dim=1.2, ideal_area=4.2, max_area=7.5,
        aspect_max=2.6, zone=PRIVATE, habitable=False, wet=True,
        color="#d8eef0", priority=88,
    ),
    "toilet": dict(
        label="Toilet", min_area=1.4, min_dim=0.9, ideal_area=2.2, max_area=4.0,
        aspect_max=3.0, zone=SERVICE, habitable=False, wet=True,
        color="#dcf0f2", priority=60,
    ),
    "staircase": dict(
        label="Staircase", min_area=6.5, min_dim=2.3, ideal_area=8.0, max_area=12.0,
        aspect_max=1.8, zone=CIRCULATION, habitable=False, wet=False,
        color="#dfe3e8", priority=99,
    ),
    "corridor": dict(
        label="Corridor", min_area=1.5, min_dim=1.0, ideal_area=4.0, max_area=12.0,
        aspect_max=6.0, zone=CIRCULATION, habitable=False, wet=False,
        color="#eceff3", priority=35,
    ),
    "parking": dict(
        label="Parking", min_area=12.5, min_dim=2.5, ideal_area=13.5, max_area=40.0,
        aspect_max=3.2, zone=OUTDOOR, habitable=False, wet=False,
        color="#e2e5e9", priority=97,
    ),
    "balcony": dict(
        label="Balcony", min_area=2.2, min_dim=1.1, ideal_area=4.0, max_area=9.0,
        aspect_max=4.0, zone=OUTDOOR, habitable=False, wet=False,
        color="#dff0e4", priority=25,
    ),
    "terrace": dict(
        label="Terrace", min_area=4.0, min_dim=1.5, ideal_area=12.0, max_area=60.0,
        aspect_max=5.0, zone=OUTDOOR, habitable=False, wet=False,
        color="#e7f3ea", priority=20,
    ),
    "headroom": dict(
        label="Head Room", min_area=4.0, min_dim=1.8, ideal_area=7.0, max_area=12.0,
        aspect_max=2.4, zone=CIRCULATION, habitable=False, wet=False,
        color="#e4e7ea", priority=60,
    ),
}

DEFAULT_SPACE = dict(
    label="Room", min_area=5.0, min_dim=1.8, ideal_area=9.0, max_area=18.0,
    aspect_max=2.5, zone=PUBLIC, habitable=True, wet=False,
    color="#e6e6e6", priority=50,
)


def spec(space_type: str) -> dict:
    """Return the standards record for a space type (never raises)."""
    return SPACE_STANDARDS.get(space_type, DEFAULT_SPACE)


def label_for(space_type: str) -> str:
    return spec(space_type)["label"]


# --------------------------------------------------------------------------
# Topological relationships
# --------------------------------------------------------------------------
# Positive weight  -> the two spaces should share a wall (and usually a door).
# Negative weight  -> the two spaces should NOT be directly connected.
# required=True    -> failing this adjacency is a validation ERROR, not a hint.
ADJACENCY_RULES: list[dict] = [
    dict(a="kitchen", b="dining", weight=10, required=True, door=True,
         why="Food must travel from kitchen to dining without crossing the living room."),
    dict(a="dining", b="living", weight=8, required=True, door=True,
         why="Living and dining form the continuous public zone of the house."),
    dict(a="living", b="foyer", weight=10, required=True, door=True,
         why="The entrance must open into the living space, not into a private room."),
    dict(a="foyer", b="staircase", weight=9, required=True, door=True,
         why="Vertical circulation must be reachable from the entrance lobby."),
    dict(a="parking", b="foyer", weight=9, required=True, door=False,
         why="Occupants should reach the entrance from parking under cover."),
    dict(a="master_bedroom", b="bathroom", weight=10, required=True, door=True,
         why="The master bedroom needs an attached bathroom."),
    dict(a="bedroom", b="bathroom", weight=9, required=False, door=True,
         why="Each bedroom should have a bathroom on the same floor, ideally adjacent."),
    dict(a="kitchen", b="utility", weight=8, required=False, door=True,
         why="Utility and wash area work as a service extension of the kitchen."),
    dict(a="kitchen", b="store", weight=6, required=False, door=True,
         why="Dry store is most useful directly off the kitchen."),
    dict(a="staircase", b="living", weight=6, required=False, door=True,
         why="A stair landing opening into the living space keeps circulation short."),
    dict(a="toilet", b="foyer", weight=5, required=False, door=True,
         why="A powder room near the entrance serves guests without entering private zones."),
    dict(a="balcony", b="living", weight=5, required=False, door=True,
         why="Outdoor access from the main living space."),
    dict(a="balcony", b="master_bedroom", weight=5, required=False, door=True,
         why="Private outdoor access from the master suite."),
    dict(a="balcony", b="bedroom", weight=4, required=False, door=True,
         why="Private outdoor access from the bedroom."),
    dict(a="pooja", b="living", weight=5, required=False, door=True,
         why="Prayer space is traditionally reached from the public zone."),
    dict(a="study", b="living", weight=3, required=False, door=True,
         why="Study benefits from quiet access off the main circulation."),

    # --- separations -------------------------------------------------------
    dict(a="kitchen", b="bathroom", weight=-7, required=False, door=False,
         why="Hygiene: a kitchen should not share a door or wall with a bathroom."),
    dict(a="kitchen", b="toilet", weight=-7, required=False, door=False,
         why="Hygiene: a kitchen should not share a door or wall with a toilet."),
    dict(a="pooja", b="bathroom", weight=-9, required=False, door=False,
         why="Prayer space adjoining a bathroom is culturally unacceptable in Indian practice."),
    dict(a="pooja", b="toilet", weight=-9, required=False, door=False,
         why="Prayer space adjoining a toilet is culturally unacceptable in Indian practice."),
    dict(a="master_bedroom", b="kitchen", weight=-4, required=False, door=False,
         why="Cooking noise and heat next to the master bedroom is undesirable."),
    dict(a="parking", b="bedroom", weight=-3, required=False, door=False,
         why="Vehicle noise and fumes next to a bedroom is undesirable."),
]


def adjacency_weight(type_a: str, type_b: str) -> tuple[float, bool, str]:
    """Affinity between two space types -> (weight, required, rationale)."""
    for rule in ADJACENCY_RULES:
        if (rule["a"] == type_a and rule["b"] == type_b) or (rule["a"] == type_b and rule["b"] == type_a):
            return rule["weight"], rule["required"], rule["why"]
    # Spaces in the same zone have a mild attraction; cross-zone pairs are neutral.
    za, zb = spec(type_a)["zone"], spec(type_b)["zone"]
    return (1.0, False, "Spaces in the same functional zone") if za == zb else (0.0, False, "")


# --------------------------------------------------------------------------
# Construction geometry
# --------------------------------------------------------------------------
WALL_EXTERIOR = 0.230     # 9 inch brick
WALL_INTERIOR = 0.115     # 4.5 inch brick
FLOOR_TO_FLOOR = 3.15     # slab top to slab top
CEILING_HEIGHT = 2.90     # NBC minimum for a habitable room is 2.75 m
SLAB_THICKNESS = 0.150
DOOR_WIDTH_MAIN = 1.05
DOOR_WIDTH = 0.90
DOOR_WIDTH_SMALL = 0.75   # bathrooms, toilets, stores
DOOR_HEIGHT = 2.10
WINDOW_HEIGHT = 1.35
WINDOW_SILL = 0.90
PARAPET_HEIGHT = 1.05
MIN_OPENING_WALL = 0.95   # a shared wall shorter than this cannot host a door
GRID = 0.025              # all geometry snapped to 25 mm

# NBC light and ventilation: openings of at least 1/10 of the floor area.
LIGHT_VENT_RATIO = 0.10

# Vehicle
CAR_WIDTH = 2.50
CAR_LENGTH = 5.00
CAR_BAY_WIDTH = 2.75      # includes door-swing clearance

# Staircase (dog-legged, typical Indian residential)
STAIR_WIDTH = 2.40        # two 1.0 m flights plus a 0.4 m well
STAIR_LENGTH = 3.30
STAIR_RISER = 0.165
STAIR_TREAD = 0.280

# Development control (overridable by the client)
DEFAULT_MAX_GROUND_COVERAGE = 0.65   # fraction of plot area
DEFAULT_MAX_FAR = 2.00               # total built-up divided by plot area
MAX_BALCONY_PROJECTION_RATIO = 0.50  # a balcony may cantilever into half the setback


# --------------------------------------------------------------------------
# Cost model (indicative, Tier-2 Indian city, 2026 assumptions)
# --------------------------------------------------------------------------
# Every line item exposes its own driver and rate so the UI can show the
# arithmetic instead of a black-box number.
COST_ITEMS: list[dict] = [
    dict(key="earthwork", label="Excavation & earthwork", driver="footprint_area",
         rate=650, unit="per m2 footprint",
         note="Excavation, PCC bed, anti-termite treatment, backfill."),
    dict(key="foundation", label="Foundation & plinth", driver="footprint_area",
         rate=2900, unit="per m2 footprint",
         note="Isolated footings, columns up to plinth, plinth beam, filling."),
    dict(key="structure", label="RCC frame & slabs", driver="builtup_area",
         rate=5600, unit="per m2 built-up",
         note="Columns, beams, slabs and stair waist slab: steel, concrete and shuttering."),
    dict(key="masonry", label="Masonry & plaster", driver="wall_area",
         rate=900, unit="per m2 wall face",
         note="Brick and block walls with internal and external plaster, both faces measured."),
    dict(key="flooring", label="Flooring & tiling", driver="builtup_area",
         rate=1350, unit="per m2 built-up",
         note="Vitrified tile in dry areas, anti-skid in wet areas, skirting."),
    dict(key="joinery", label="Doors & windows", driver="opening_count",
         rate=13500, unit="per opening",
         note="Frames, shutters, hardware, glazing and grills averaged over all openings."),
    dict(key="plumbing", label="Plumbing & sanitary", driver="wet_room_count",
         rate=48000, unit="per wet space",
         note="Supply and drainage lines plus CP and sanitary fittings per wet space."),
    dict(key="electrical", label="Electrical & data", driver="builtup_area",
         rate=750, unit="per m2 built-up",
         note="Conduiting, wiring, distribution board, switchgear, fixtures, data points."),
    dict(key="painting", label="Painting & finishes", driver="wall_area",
         rate=320, unit="per m2 wall face",
         note="Putty, primer and two coats emulsion inside, exterior-grade finish outside."),
    dict(key="waterproof", label="Roof & waterproofing", driver="roof_area",
         rate=700, unit="per m2 roof",
         note="Brickbat coba or membrane, weathering course, parapet finish, rainwater outlets."),
    dict(key="paving", label="Parking, compound & paving", driver="site_work_area",
         rate=950, unit="per m2 open area",
         note="Paver block driveway, compound wall share, gate, landscape base."),
]

COST_PERCENT_ITEMS: list[dict] = [
    dict(key="prelims", label="Site preliminaries & overheads", pct=0.030,
         note="Site office, water, power, hoarding, temporary works, supervision."),
    dict(key="fees", label="Design & statutory fees", pct=0.055,
         note="Architectural and structural consultancy, plan sanction, development charges."),
    dict(key="contingency", label="Contingency", pct=0.050,
         note="Allowance for rate variation and scope not yet frozen."),
    dict(key="gst", label="GST on works contract", pct=0.090,
         note="Indicative composite rate on the construction contract value."),
]

QUALITY_FACTOR = {"economy": 0.82, "standard": 1.00, "premium": 1.34, "luxury": 1.75}
CITY_FACTOR = {"tier1": 1.18, "tier2": 1.00, "tier3": 0.89}
QUALITY_LABEL = {
    "economy": "Economy", "standard": "Standard", "premium": "Premium", "luxury": "Luxury",
}
CITY_LABEL = {"tier1": "Metro / Tier 1", "tier2": "Tier 2 city", "tier3": "Tier 3 / town"}

# Open (unroofed) spaces cost less per m2 than enclosed floor area.
AREA_WEIGHT = {"parking": 0.42, "balcony": 0.55, "terrace": 0.30}
