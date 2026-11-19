"""Rulebook: room modules, adjacency rules, building standards and pricing.

The rulebook lives in an Excel workbook (rules/barndo_rules.xlsx) so the design
team can edit it without touching code. The defaults below are used to create
that workbook the first time and as a fallback when a value is missing.

Module dimension convention (important):
    w = width measured ALONG the wall that holds the room's entry door
    d = depth measured from that door wall INTO the room (toward the back wall)
All lengths are in feet.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import RULEBOOK_PATH, MODULES_DIR

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------
MODULE_COLUMNS = [
    "id", "name", "category", "min_w", "max_w", "min_d", "max_d", "pref_w", "pref_d",
    "wet", "needs_exterior", "windows", "window_units", "window_w", "door_w",
    "finish_cost_sqft", "fixture_cost", "dxf_file", "fixture_anchor", "color",
]

# Sizes are nominal (wall centre-line / outside face). The Company Rules sheet checks
# CLEAR (finished) sizes, so minimums here are set a little above the clear minimums.
# windows = number of window openings, window_units = 1 (single 3x4) or 2 (double 3x4 pair).
DEFAULT_MODULES: list[dict[str, Any]] = [
    dict(id="great_room", name="Kitchen / Dining / Living", category="living", min_w=14, max_w=50, min_d=18, max_d=70, pref_w=26, pref_d=36, wet=True, needs_exterior=True, windows=3, window_units=2, window_w=3, door_w=3, finish_cost_sqft=55, fixture_cost=28000, dxf_file="great_room.dxf", fixture_anchor="back-center", color="#F6E7C8"),
    dict(id="master_bedroom", name="Primary Bedroom", category="bedroom", min_w=13, max_w=18, min_d=13, max_d=18, pref_w=15, pref_d=15, wet=False, needs_exterior=True, windows=1, window_units=2, window_w=3, door_w=3, finish_cost_sqft=32, fixture_cost=0, dxf_file="master_bedroom.dxf", fixture_anchor="back-center", color="#DCE8F5"),
    dict(id="master_bath", name="Primary Bath", category="bath", min_w=8, max_w=14, min_d=8, max_d=14, pref_w=10, pref_d=10, wet=True, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.67, finish_cost_sqft=115, fixture_cost=14000, dxf_file="master_bath.dxf", fixture_anchor="back-center", color="#D7EFEA"),
    dict(id="master_wic", name="Walk-in Closet", category="storage", min_w=5, max_w=16, min_d=5, max_d=12, pref_w=7, pref_d=8, wet=False, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.33, finish_cost_sqft=25, fixture_cost=1200, dxf_file="master_wic.dxf", fixture_anchor="back-left", color="#ECE6F3"),
    dict(id="bedroom", name="Bedroom", category="bedroom", min_w=12.75, max_w=16, min_d=12.75, max_d=16, pref_w=13, pref_d=13, wet=False, needs_exterior=True, windows=1, window_units=1, window_w=3, door_w=2.67, finish_cost_sqft=30, fixture_cost=0, dxf_file="bedroom.dxf", fixture_anchor="back-center", color="#DCE8F5"),
    dict(id="full_bath", name="Bath", category="bath", min_w=8, max_w=12, min_d=6, max_d=13, pref_w=8.5, pref_d=7, wet=True, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.5, finish_cost_sqft=110, fixture_cost=7500, dxf_file="full_bath.dxf", fixture_anchor="back-center", color="#D7EFEA"),
    dict(id="half_bath", name="Half Bath", category="bath", min_w=5.75, max_w=9, min_d=5.75, max_d=13, pref_w=6, pref_d=6, wet=True, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.33, finish_cost_sqft=95, fixture_cost=3000, dxf_file="half_bath.dxf", fixture_anchor="back-left", color="#D7EFEA"),
    dict(id="laundry_mud", name="Laundry / Mudroom", category="utility", min_w=6, max_w=12, min_d=6, max_d=14, pref_w=8, pref_d=9, wet=True, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.67, finish_cost_sqft=55, fixture_cost=3300, dxf_file="laundry_mud.dxf", fixture_anchor="back-left", color="#E9EEDB"),
    dict(id="pantry", name="Pantry", category="utility", min_w=4, max_w=8, min_d=4, max_d=14, pref_w=5, pref_d=6, wet=False, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.33, finish_cost_sqft=40, fixture_cost=900, dxf_file="pantry.dxf", fixture_anchor="back-left", color="#E9EEDB"),
    dict(id="office", name="Office", category="bedroom", min_w=10, max_w=14, min_d=10, max_d=14, pref_w=11, pref_d=11, wet=False, needs_exterior=True, windows=1, window_units=1, window_w=3, door_w=2.67, finish_cost_sqft=30, fixture_cost=0, dxf_file="office.dxf", fixture_anchor="back-center", color="#E3EAF2"),
    dict(id="flex", name="Flex / Bonus Room", category="living", min_w=11, max_w=22, min_d=11, max_d=22, pref_w=15, pref_d=15, wet=False, needs_exterior=True, windows=2, window_units=1, window_w=3, door_w=3, finish_cost_sqft=32, fixture_cost=0, dxf_file="flex.dxf", fixture_anchor="center", color="#F3E9DD"),
    dict(id="storage", name="Storage", category="storage", min_w=2, max_w=12, min_d=2, max_d=16, pref_w=4, pref_d=4, wet=False, needs_exterior=False, windows=0, window_units=1, window_w=3, door_w=2.33, finish_cost_sqft=15, fixture_cost=0, dxf_file="", fixture_anchor="back-left", color="#EFEFEF"),
]

ADJ_COLUMNS = ["room_a", "room_b", "relation", "weight", "note"]
DEFAULT_ADJACENCY: list[dict[str, Any]] = [
    dict(room_a="pantry", room_b="great_room", relation="prefer", weight=3, note="Pantry opens to the kitchen"),
    dict(room_a="laundry_mud", room_b="shop", relation="prefer", weight=3, note="Drop zone / wash-up between shop and house"),
    dict(room_a="laundry_mud", room_b="master_wic", relation="prefer", weight=1.5, note="Laundry near primary closet"),
    dict(room_a="half_bath", room_b="great_room", relation="prefer", weight=1, note="Guest powder room near living"),
    dict(room_a="bedroom", room_b="laundry_mud", relation="avoid", weight=1, note="Machine noise"),
    dict(room_a="master_bedroom", room_b="bedroom", relation="avoid", weight=1, note="Privacy - split plan"),
    dict(room_a="bedroom", room_b="shop", relation="avoid", weight=2, note="Shop noise / fumes"),
    dict(room_a="master_bedroom", room_b="shop", relation="avoid", weight=2, note="Shop noise / fumes"),
    dict(room_a="full_bath", room_b="bedroom", relation="prefer", weight=1, note="Bath near bedrooms"),
]

BUILDING_COLUMNS = ["key", "value", "note"]
DEFAULT_BUILDING: list[dict[str, Any]] = [
    dict(key="bay_spacing", value=10, note="Post / column spacing along exterior walls (ft)"),
    dict(key="post_size", value=0.5, note="Post size (ft) - 6x6 = 0.5"),
    dict(key="ext_wall", value=0.5, note="Exterior wall thickness (ft) - company standard 6 in (rule 12)"),
    dict(key="int_wall", value=0.333, note="Interior wall thickness (ft) - company standard 4 in (rule 12)"),
    dict(key="shop_wall", value=0.333, note="Shop / living separation wall (ft) - raise if you build it fire-rated"),
    dict(key="hall_width", value=4, note="Hallway width (ft)"),
    dict(key="link_width", value=4, note="Width of hallway links into the great room / shop (ft)"),
    dict(key="door_height", value=6.667, note="Door height (ft) - 6'-8\" (rule 5)"),
    dict(key="entry_single_w", value=3, note="Main entrance, single door width (ft) (rule 5)"),
    dict(key="entry_double_w", value=6, note="Main entrance, double door width (ft) (rule 5)"),
    dict(key="ext_door_w", value=3, note="Other exterior man-door width (ft)"),
    dict(key="door_corner_offset", value=0.333, note="Door jamb distance from the corner of the wall (ft) (rule 3)"),
    dict(key="window_w", value=3, note="Standard window width (ft) - 3x4 (rule 4)"),
    dict(key="window_h", value=4, note="Standard window height (ft) - 3x4 (rule 4)"),
    dict(key="overhead_door_w", value=12, note="Shop overhead door width (ft)"),
    dict(key="overhead_door_h", value=12, note="Shop overhead door height (ft)"),
    dict(key="opening_clearance", value=0.25, note="Min. clear distance from a post to a door/window rough opening (ft)"),
    dict(key="eave_height", value=12, note="Standard eave height (ft) (rule 11)"),
    dict(key="roof_pitch", value=4, note="Standard roof slope, rise per 12 (4 = 4:12) (rule 11)"),
    dict(key="roof_overhang", value=1, note="Roof overhang at eaves and gables (ft)"),
    dict(key="col_a_depths", value="13,14,15,16,17", note="Candidate depths of the outer room column (ft)"),
    dict(key="col_b_depths", value="0,6,7,8,9,10,11,12,13", note="Candidate depths of the inner room column, 0 = none (ft)"),
    dict(key="min_shop_length", value=12, note="Smallest shop length allowed (ft)"),
]

PRICING_COLUMNS = ["key", "value", "note"]
DEFAULT_PRICING: list[dict[str, Any]] = [
    dict(key="structure_sqft", value=18, note="Post-frame / steel structure per sqft of floor ($/sqft)"),
    dict(key="wall_cladding_sqft", value=9, note="Exterior wall girts + metal siding per sqft of wall area, uses eave height ($/sqft)"),
    dict(key="roof_sqft", value=11, note="Trusses, purlins + metal roof per sqft of sloped roof area, uses slope ($/sqft)"),
    dict(key="insulation_sqft", value=3.5, note="Spray foam on walls + roof around the living area ($/sqft of surface)"),
    dict(key="slab_sqft", value=9, note="Concrete slab under building ($/sqft)"),
    dict(key="porch_sqft", value=28, note="Covered porch incl. slab ($/sqft)"),
    dict(key="interior_wall_lf", value=48, note="Framed + finished interior wall ($/linear ft)"),
    dict(key="interior_door", value=450, note="Interior door 6'-8\" installed ($ each)"),
    dict(key="exterior_door", value=1800, note="Exterior single door installed ($ each)"),
    dict(key="exterior_door_double", value=3600, note="Exterior double door installed ($ each)"),
    dict(key="overhead_door", value=3800, note="Overhead / roll-up door installed ($ each)"),
    dict(key="window", value=650, note="Standard 3x4 window installed ($ per unit; a double = 2 units)"),
    dict(key="mep_living_sqft", value=22, note="Plumbing / electrical / HVAC rough + finish, living ($/sqft)"),
    dict(key="mep_shop_sqft", value=6, note="Electrical / lighting, shop ($/sqft)"),
    dict(key="contingency_pct", value=10, note="Contingency (%)"),
]

# Company rules: every generated plan is checked against these before it is shown.
# check = which built-in check runs (see barndo/design_rules.py). severity: hard = plan is
# rejected if it fails, soft = plan is kept but flagged. enabled: Y/N.
RULE_COLUMNS = ["id", "rule", "check", "applies_to", "value", "severity", "enabled"]
DEFAULT_RULES: list[dict[str, Any]] = [
    dict(id=1, rule="Each full bath has at least a sink, toilet and shower", check="required_fixtures", applies_to="full_bath,master_bath", value="sink,toilet,shower", severity="hard", enabled=True),
    dict(id=2, rule="No hallway when the doors can open to an open space", check="no_unneeded_hallway", applies_to="", value="", severity="hard", enabled=True),
    dict(id=3, rule="Doors sit at the side of the wall, not in the middle", check="doors_near_corner", applies_to="interior", value=1.0, severity="hard", enabled=True),
    dict(id=4, rule="Standard windows 3x4; double windows in primary bedroom, living area and kitchen", check="window_standard", applies_to="master_bedroom,living,kitchen", value="3x4", severity="hard", enabled=True),
    dict(id=5, rule="Doors 6'-8\" high; main entrance single 3' or double 6'", check="door_standard", applies_to="", value="6.667", severity="hard", enabled=True),
    dict(id=6, rule="Laundry and mudroom are one room; bedrooms, kitchen, office and living have windows", check="laundry_mud_and_windows", applies_to="bedroom,master_bedroom,office,flex,kitchen,living", value="", severity="hard", enabled=True),
    dict(id=7, rule="Every bedroom is at least 12' x 12' (clear)", check="min_clear_size", applies_to="bedroom,master_bedroom", value="12x12", severity="hard", enabled=True),
    dict(id=8, rule="Bathrooms are at least 5'-4\" wide (clear)", check="min_clear_width", applies_to="full_bath,master_bath,half_bath", value=5.333, severity="hard", enabled=True),
    dict(id=9, rule="Keep walkways to a minimum", check="max_circulation_pct", applies_to="", value=12, severity="soft", enabled=True),
    dict(id=10, rule="Cost estimates include eave height and roof slope", check="estimate_uses_eave_and_slope", applies_to="", value="", severity="hard", enabled=True),
    dict(id=11, rule="Standard 12' eave and 4:12 slope", check="building_standard", applies_to="", value="eave_height=12,roof_pitch=4", severity="soft", enabled=True),
    dict(id=12, rule="Exterior walls 6\", interior walls 4\"", check="wall_thickness", applies_to="", value="ext=0.5,int=0.333", severity="hard", enabled=True),
    dict(id=13, rule="Every door swings clear of fixtures, furniture and other doors", check="door_swing_clear", applies_to="", value="", severity="hard", enabled=True),
]

DEFAULT_FOOTPRINTS = [(30, 40), (30, 50), (40, 50), (40, 60), (40, 70), (40, 80), (50, 60), (50, 80), (50, 100), (60, 100)]


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------
@dataclass
class Module:
    id: str
    name: str
    category: str
    min_w: float
    max_w: float
    min_d: float
    max_d: float
    pref_w: float
    pref_d: float
    wet: bool = False
    needs_exterior: bool = False
    windows: int = 0
    window_units: int = 1
    window_w: float = 3.0
    door_w: float = 2.67
    finish_cost_sqft: float = 30.0
    fixture_cost: float = 0.0
    dxf_file: str = ""
    fixture_anchor: str = "back-center"
    color: str = "#EEEEEE"

    def fits(self, w: float, d: float, tol: float = 1e-6) -> bool:
        return (self.min_w - tol <= w <= self.max_w + tol) and (self.min_d - tol <= d <= self.max_d + tol)

    @property
    def dxf_path(self) -> Path | None:
        return (MODULES_DIR / self.dxf_file) if self.dxf_file else None


@dataclass
class AdjRule:
    room_a: str
    room_b: str
    relation: str  # prefer | avoid
    weight: float = 1.0
    note: str = ""


@dataclass
class CompanyRule:
    id: str
    rule: str
    check: str
    applies_to: list[str] = field(default_factory=list)
    value: Any = ""
    severity: str = "hard"
    enabled: bool = True


@dataclass
class Rulebook:
    modules: dict[str, Module]
    adjacency: list[AdjRule]
    building: dict[str, Any]
    pricing: dict[str, float]
    footprints: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_FOOTPRINTS))
    rules: list[CompanyRule] = field(default_factory=list)
    source: str = "defaults"

    def m(self, module_id: str) -> Module:
        return self.modules[module_id]

    def b(self, key: str) -> float:
        return float(self.building[key])

    def float_list(self, key: str) -> list[float]:
        raw = self.building[key]
        if isinstance(raw, (int, float)):
            return [float(raw)]
        return [float(x) for x in str(raw).replace(";", ",").split(",") if str(x).strip()]

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "modules": [asdict(m) for m in self.modules.values()],
            "adjacency": [asdict(a) for a in self.adjacency],
            "building": self.building,
            "pricing": self.pricing,
            "footprints": self.footprints,
            "rules": [asdict(r) for r in self.rules],
        }


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
_BOOL_TRUE = {"y", "yes", "true", "1", "x"}


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in _BOOL_TRUE


def _module_from_row(row: dict[str, Any]) -> Module:
    defaults = {m["id"]: m for m in DEFAULT_MODULES}.get(str(row.get("id")), {})
    data: dict[str, Any] = {}
    for col in MODULE_COLUMNS:
        v = row.get(col)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            v = defaults.get(col, Module.__dataclass_fields__[col].default if col in Module.__dataclass_fields__ else None)
        data[col] = v
    for col in ("min_w", "max_w", "min_d", "max_d", "pref_w", "pref_d", "window_w", "door_w", "finish_cost_sqft", "fixture_cost"):
        data[col] = float(data[col] or 0)
    data["windows"] = int(float(data["windows"] or 0))
    data["window_units"] = max(1, int(float(data.get("window_units") or 1)))
    data["wet"] = _to_bool(data["wet"])
    data["needs_exterior"] = _to_bool(data["needs_exterior"])
    data["dxf_file"] = str(data["dxf_file"] or "")
    data["id"] = str(data["id"]).strip()
    return Module(**data)


def _read_sheet(wb, name: str) -> list[dict[str, Any]]:
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for r in rows[1:]:
        if r is None or all(v is None or str(v).strip() == "" for v in r):
            continue
        out.append({header[i]: r[i] for i in range(min(len(header), len(r))) if header[i]})
    return out


def _rule_from_row(r: dict[str, Any]) -> CompanyRule:
    rid = r.get("id")
    rid = str(int(rid)) if isinstance(rid, (int, float)) else str(rid or "").strip()
    applies = [x.strip() for x in str(r.get("applies_to") or "").split(",") if x.strip()]
    return CompanyRule(id=rid, rule=str(r.get("rule") or ""), check=str(r.get("check") or "").strip(),
                       applies_to=applies, value=r.get("value") if r.get("value") is not None else "",
                       severity=str(r.get("severity") or "hard").strip().lower(),
                       enabled=_to_bool(r.get("enabled", True)) if r.get("enabled") is not None else True)


def default_rulebook() -> Rulebook:
    return Rulebook(
        modules={m["id"]: _module_from_row(m) for m in DEFAULT_MODULES},
        adjacency=[AdjRule(**a) for a in DEFAULT_ADJACENCY],
        building={r["key"]: r["value"] for r in DEFAULT_BUILDING},
        pricing={r["key"]: float(r["value"]) for r in DEFAULT_PRICING},
        rules=[_rule_from_row(r) for r in DEFAULT_RULES],
    )


def load_rulebook(path: Path | str | None = None) -> Rulebook:
    """Load the Excel rulebook, filling any gaps from the defaults."""
    path = Path(path) if path else RULEBOOK_PATH
    rb = default_rulebook()
    if not path.exists():
        return rb
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    mod_rows = _read_sheet(wb, "Modules")
    if mod_rows:
        mods = {}
        for row in mod_rows:
            if row.get("id"):
                m = _module_from_row(row)
                mods[m.id] = m
        # required modules must exist
        for req in ("great_room", "master_bedroom", "master_bath", "bedroom", "full_bath", "storage", "laundry_mud"):
            mods.setdefault(req, rb.modules[req])
        rb.modules = mods
    adj_rows = _read_sheet(wb, "Adjacency")
    if adj_rows:
        rb.adjacency = [
            AdjRule(str(r["room_a"]).strip(), str(r["room_b"]).strip(), str(r.get("relation") or "prefer").strip().lower(),
                    float(r.get("weight") or 1), str(r.get("note") or ""))
            for r in adj_rows if r.get("room_a") and r.get("room_b")
        ]
    for row in _read_sheet(wb, "Building"):
        if row.get("key"):
            rb.building[str(row["key"]).strip()] = row.get("value")
    for row in _read_sheet(wb, "Pricing"):
        if row.get("key") and row.get("value") is not None:
            rb.pricing[str(row["key"]).strip()] = float(row["value"])
    rule_rows = _read_sheet(wb, "Company Rules")
    if rule_rows:
        rb.rules = [_rule_from_row(r) for r in rule_rows if r.get("check")]
    fp_rows = _read_sheet(wb, "Footprints")
    if fp_rows:
        fps = []
        for r in fp_rows:
            try:
                fps.append((int(float(r["width"])), int(float(r["length"]))))
            except (KeyError, TypeError, ValueError):
                continue
        if fps:
            rb.footprints = fps
    rb.source = str(path)
    return rb


def write_default_rulebook(path: Path | str | None = None, overwrite: bool = False) -> Path:
    """Create the editable Excel rulebook from the defaults."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation

    path = Path(path) if path else RULEBOOK_PATH
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="5B3A1E")

    def sheet(title, columns, rows, widths=None, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(columns)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center")
        for r in rows:
            ws.append([("Y" if r.get(c) is True else "N" if r.get(c) is False else r.get(c)) for c in columns])
        for i, col in enumerate(columns, start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = (widths or {}).get(col, max(10, len(col) + 2))
        ws.freeze_panes = "A2"
        return ws

    ws = sheet("Modules", MODULE_COLUMNS, DEFAULT_MODULES, {"name": 26, "dxf_file": 20, "id": 16}, first=True)
    yn = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(yn)
    yn.add("J2:K200")
    anchor = DataValidation(type="list", formula1='"back-center,back-left,back-right,center"', allow_blank=True)
    ws.add_data_validation(anchor)
    anchor.add("S2:S200")
    ws2 = sheet("Adjacency", ADJ_COLUMNS, DEFAULT_ADJACENCY, {"note": 40})
    rel = DataValidation(type="list", formula1='"prefer,avoid"', allow_blank=False)
    ws2.add_data_validation(rel)
    rel.add("C2:C500")
    sheet("Building", BUILDING_COLUMNS, DEFAULT_BUILDING, {"key": 20, "value": 22, "note": 60})
    sheet("Pricing", PRICING_COLUMNS, DEFAULT_PRICING, {"key": 22, "value": 12, "note": 70})
    ws4 = sheet("Company Rules", RULE_COLUMNS, DEFAULT_RULES, {"rule": 70, "check": 28, "applies_to": 40, "value": 22})
    sev = DataValidation(type="list", formula1='"hard,soft"', allow_blank=False)
    ws4.add_data_validation(sev)
    sev.add("F2:F500")
    yn2 = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws4.add_data_validation(yn2)
    yn2.add("G2:G500")
    sheet("Footprints", ["width", "length"], [dict(width=w, length=l) for w, l in DEFAULT_FOOTPRINTS])
    readme = wb.create_sheet("README", 0)
    lines = [
        "BARNDO PLANNER RULEBOOK",
        "",
        "Edit these sheets to change how the layout engine designs plans. Restart the app (or POST /api/admin/reload) after saving.",
        "",
        "Modules: one row per room type (a puzzle piece).",
        "  w = width ALONG the wall with the room's entry door; d = depth INTO the room. Feet.",
        "  min/max = hard limits the engine will never break. pref = the size it aims for.",
        "  needs_exterior = room must touch an outside wall (bedrooms need egress windows).",
        "  dxf_file = fixture/furniture drawing in /modules (inches, origin bottom-left, door wall at the bottom).",
        "  fixture_anchor = where that drawing sits in the room when the room is larger than the drawing.",
        "Adjacency: preferred / avoided neighbours. 'shop' and 'great_room' can be used as room names.",
        "Building: construction standards (post spacing, wall thickness, hall width...).",
        "Pricing: budget-level cost rates used for the estimate. PLACEHOLDER VALUES - replace with your own.",
        "Footprints: standard building sizes offered in the configurator (width x length).",
        "Company Rules: every plan is checked against these before it is shown. hard = plans that break it are never shown,",
        "  soft = shown with a warning. To add a rule, add a row and pick a 'check' type (see the list in README / Company Rules).",
        "  Example: id 13 | Offices at least 10x10 | min_clear_size | office | 10x10 | hard | Y",
    ]
    for ln in lines:
        readme.append([ln])
    readme["A1"].font = Font(bold=True, size=14)
    readme.column_dimensions["A"].width = 120
    wb.save(path)
    return path
