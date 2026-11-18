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
    "wet", "needs_exterior", "windows", "window_w", "door_w",
    "finish_cost_sqft", "fixture_cost", "dxf_file", "fixture_anchor", "color",
]

DEFAULT_MODULES: list[dict[str, Any]] = [
    # id, name, category, min_w, max_w, min_d, max_d, pref_w, pref_d, wet, ext, windows, window_w, door_w, finish, fixture, dxf, anchor, color
    dict(id="great_room", name="Kitchen / Dining / Living", category="living", min_w=16, max_w=50, min_d=18, max_d=70, pref_w=26, pref_d=36, wet=True, needs_exterior=True, windows=4, window_w=4, door_w=3, finish_cost_sqft=55, fixture_cost=28000, dxf_file="great_room.dxf", fixture_anchor="back-center", color="#F6E7C8"),
    dict(id="master_bedroom", name="Primary Bedroom", category="bedroom", min_w=12, max_w=18, min_d=12, max_d=18, pref_w=15, pref_d=14, wet=False, needs_exterior=True, windows=2, window_w=3, door_w=2.67, finish_cost_sqft=32, fixture_cost=0, dxf_file="master_bedroom.dxf", fixture_anchor="back-center", color="#DCE8F5"),
    dict(id="master_bath", name="Primary Bath", category="bath", min_w=7, max_w=14, min_d=7, max_d=14, pref_w=10, pref_d=10, wet=True, needs_exterior=False, windows=1, window_w=2, door_w=2.67, finish_cost_sqft=115, fixture_cost=14000, dxf_file="master_bath.dxf", fixture_anchor="back-center", color="#D7EFEA"),
    dict(id="master_wic", name="Walk-in Closet", category="storage", min_w=5, max_w=16, min_d=5, max_d=12, pref_w=7, pref_d=8, wet=False, needs_exterior=False, windows=0, window_w=0, door_w=2.33, finish_cost_sqft=25, fixture_cost=1200, dxf_file="master_wic.dxf", fixture_anchor="back-left", color="#ECE6F3"),
    dict(id="bedroom", name="Bedroom", category="bedroom", min_w=10, max_w=15, min_d=10, max_d=15, pref_w=12, pref_d=12, wet=False, needs_exterior=True, windows=1, window_w=3, door_w=2.67, finish_cost_sqft=30, fixture_cost=0, dxf_file="bedroom.dxf", fixture_anchor="back-center", color="#DCE8F5"),
    dict(id="full_bath", name="Bath", category="bath", min_w=7, max_w=12, min_d=5, max_d=13, pref_w=8, pref_d=7, wet=True, needs_exterior=False, windows=1, window_w=2, door_w=2.5, finish_cost_sqft=110, fixture_cost=7500, dxf_file="full_bath.dxf", fixture_anchor="back-left", color="#D7EFEA"),
    dict(id="half_bath", name="Half Bath", category="bath", min_w=4, max_w=8, min_d=4, max_d=10, pref_w=5, pref_d=5, wet=True, needs_exterior=False, windows=0, window_w=0, door_w=2.33, finish_cost_sqft=95, fixture_cost=3000, dxf_file="half_bath.dxf", fixture_anchor="back-left", color="#D7EFEA"),
    dict(id="laundry", name="Laundry", category="utility", min_w=5, max_w=10, min_d=5, max_d=14, pref_w=7, pref_d=8, wet=True, needs_exterior=False, windows=0, window_w=0, door_w=2.67, finish_cost_sqft=55, fixture_cost=1800, dxf_file="laundry.dxf", fixture_anchor="back-left", color="#E9EEDB"),
    dict(id="mudroom", name="Mudroom", category="utility", min_w=5, max_w=10, min_d=5, max_d=14, pref_w=7, pref_d=8, wet=False, needs_exterior=False, windows=0, window_w=0, door_w=2.67, finish_cost_sqft=45, fixture_cost=1500, dxf_file="mudroom.dxf", fixture_anchor="back-left", color="#E9EEDB"),
    dict(id="pantry", name="Pantry", category="utility", min_w=4, max_w=8, min_d=4, max_d=14, pref_w=5, pref_d=6, wet=False, needs_exterior=False, windows=0, window_w=0, door_w=2.33, finish_cost_sqft=40, fixture_cost=900, dxf_file="pantry.dxf", fixture_anchor="back-left", color="#E9EEDB"),
    dict(id="office", name="Office", category="bedroom", min_w=9, max_w=14, min_d=9, max_d=14, pref_w=11, pref_d=10, wet=False, needs_exterior=True, windows=1, window_w=3, door_w=2.67, finish_cost_sqft=30, fixture_cost=0, dxf_file="office.dxf", fixture_anchor="back-center", color="#E3EAF2"),
    dict(id="flex", name="Flex / Bonus Room", category="living", min_w=10, max_w=22, min_d=10, max_d=22, pref_w=15, pref_d=15, wet=False, needs_exterior=True, windows=2, window_w=3, door_w=3, finish_cost_sqft=32, fixture_cost=0, dxf_file="flex.dxf", fixture_anchor="center", color="#F3E9DD"),
    dict(id="storage", name="Storage", category="storage", min_w=2, max_w=12, min_d=2, max_d=16, pref_w=4, pref_d=4, wet=False, needs_exterior=False, windows=0, window_w=0, door_w=2.33, finish_cost_sqft=15, fixture_cost=0, dxf_file="", fixture_anchor="back-left", color="#EFEFEF"),
]

ADJ_COLUMNS = ["room_a", "room_b", "relation", "weight", "note"]
DEFAULT_ADJACENCY: list[dict[str, Any]] = [
    dict(room_a="pantry", room_b="great_room", relation="prefer", weight=3, note="Pantry opens to the kitchen"),
    dict(room_a="laundry", room_b="master_wic", relation="prefer", weight=1.5, note="Laundry near primary closet"),
    dict(room_a="mudroom", room_b="shop", relation="prefer", weight=3, note="Drop zone between shop and house"),
    dict(room_a="laundry", room_b="shop", relation="prefer", weight=2, note="Wash up coming in from the shop"),
    dict(room_a="half_bath", room_b="great_room", relation="prefer", weight=1, note="Guest powder room near living"),
    dict(room_a="bedroom", room_b="laundry", relation="avoid", weight=1, note="Machine noise"),
    dict(room_a="master_bedroom", room_b="bedroom", relation="avoid", weight=1, note="Privacy - split plan"),
    dict(room_a="bedroom", room_b="shop", relation="avoid", weight=2, note="Shop noise / fumes"),
    dict(room_a="master_bedroom", room_b="shop", relation="avoid", weight=2, note="Shop noise / fumes"),
    dict(room_a="full_bath", room_b="bedroom", relation="prefer", weight=1, note="Bath near bedrooms"),
]

BUILDING_COLUMNS = ["key", "value", "note"]
DEFAULT_BUILDING: list[dict[str, Any]] = [
    dict(key="bay_spacing", value=10, note="Post / column spacing along exterior walls (ft)"),
    dict(key="post_size", value=0.5, note="Post size (ft) - 6x6 = 0.5"),
    dict(key="ext_wall", value=0.67, note="Exterior wall thickness (ft), drawn inside footprint"),
    dict(key="int_wall", value=0.375, note="Interior wall thickness (ft)"),
    dict(key="shop_wall", value=0.5, note="Shop / living separation wall (ft)"),
    dict(key="hall_width", value=4, note="Hallway width (ft)"),
    dict(key="link_width", value=4, note="Width of hallway links into the great room / shop (ft)"),
    dict(key="ext_door_w", value=3, note="Exterior man-door width (ft)"),
    dict(key="overhead_door_w", value=12, note="Shop overhead door width (ft)"),
    dict(key="opening_clearance", value=0.5, note="Min. clear distance from a post to a door/window (ft)"),
    dict(key="col_a_depths", value="11,12,13,14,15,16", note="Candidate depths of the outer room column (ft)"),
    dict(key="col_b_depths", value="0,5,6,7,8,9,10,11,12", note="Candidate depths of the inner room column, 0 = none (ft)"),
    dict(key="min_shop_length", value=12, note="Smallest shop length allowed (ft)"),
    dict(key="eave_height", value=12, note="Eave height (ft) - informational"),
]

PRICING_COLUMNS = ["key", "value", "note"]
DEFAULT_PRICING: list[dict[str, Any]] = [
    dict(key="shell_living_sqft", value=48, note="Post-frame / steel shell, insulated, living area ($/sqft)"),
    dict(key="shell_shop_sqft", value=32, note="Shell for shop area ($/sqft)"),
    dict(key="slab_sqft", value=9, note="Concrete slab under building ($/sqft)"),
    dict(key="porch_sqft", value=28, note="Covered porch incl. slab ($/sqft)"),
    dict(key="interior_wall_lf", value=48, note="Framed + finished interior wall ($/linear ft)"),
    dict(key="interior_door", value=450, note="Interior door installed ($ each)"),
    dict(key="exterior_door", value=1800, note="Exterior man-door installed ($ each)"),
    dict(key="overhead_door", value=3800, note="Overhead / roll-up door installed ($ each)"),
    dict(key="window", value=700, note="Window installed ($ each)"),
    dict(key="mep_living_sqft", value=22, note="Plumbing / electrical / HVAC rough + finish, living ($/sqft)"),
    dict(key="mep_shop_sqft", value=6, note="Electrical / lighting, shop ($/sqft)"),
    dict(key="contingency_pct", value=10, note="Contingency (%)"),
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
class Rulebook:
    modules: dict[str, Module]
    adjacency: list[AdjRule]
    building: dict[str, Any]
    pricing: dict[str, float]
    footprints: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_FOOTPRINTS))
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


def default_rulebook() -> Rulebook:
    return Rulebook(
        modules={m["id"]: _module_from_row(m) for m in DEFAULT_MODULES},
        adjacency=[AdjRule(**a) for a in DEFAULT_ADJACENCY],
        building={r["key"]: r["value"] for r in DEFAULT_BUILDING},
        pricing={r["key"]: float(r["value"]) for r in DEFAULT_PRICING},
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
        for req in ("great_room", "master_bedroom", "master_bath", "bedroom", "full_bath", "storage"):
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
    anchor.add("R2:R200")
    ws2 = sheet("Adjacency", ADJ_COLUMNS, DEFAULT_ADJACENCY, {"note": 40})
    rel = DataValidation(type="list", formula1='"prefer,avoid"', allow_blank=False)
    ws2.add_data_validation(rel)
    rel.add("C2:C500")
    sheet("Building", BUILDING_COLUMNS, DEFAULT_BUILDING, {"key": 20, "value": 22, "note": 60})
    sheet("Pricing", PRICING_COLUMNS, DEFAULT_PRICING, {"key": 20, "value": 12, "note": 60})
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
    ]
    for ln in lines:
        readme.append([ln])
    readme["A1"].font = Font(bold=True, size=14)
    readme.column_dimensions["A"].width = 120
    wb.save(path)
    return path
