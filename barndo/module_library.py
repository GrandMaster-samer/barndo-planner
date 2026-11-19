"""Room-module DXF library: create placeholder drawings, validate, load.

MODULE DRAWING STANDARD (give this to your drafters)
---------------------------------------------------
* One DXF per module, file name = `dxf_file` column in the rulebook.
* Units: inches ($INSUNITS = 1).
* Draw ONLY fixtures / cabinets / furniture - no walls, doors or windows.
  The engine draws walls and openings when it assembles the plan.
* Origin (0,0) = bottom-left corner of the room's MINIMUM size box
  (min_w x min_d from the rulebook).
* The room's entry-door wall is the BOTTOM edge (y = 0). The back wall is at
  y = min_d. Put beds, tubs, counters against the back wall.
* Everything must fit inside the 0..min_w*12 x 0..min_d*12 box.
* Layers: FIXTURE (plumbing, cabinets, appliances) and FURNITURE.
* Allowed entities: LINE, LWPOLYLINE, CIRCLE, ARC, TEXT, INSERT.
* Draw fixtures as BLOCKS with descriptive names - the Company Rules read them.
  A full bath must contain blocks named like SINK (or LAV/VANITY), TOILET (or WC)
  and SHOWER.

Run `python -m barndo validate-modules` to check a library.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import ezdxf

from .config import MODULES_DIR
from .rules import Rulebook

ALLOWED_LAYERS = {"FIXTURE", "FURNITURE", "0"}


# ---------------------------------------------------------------------------
# Placeholder drawings (inches)
# ---------------------------------------------------------------------------
def _rect(msp, x0, y0, x1, y1, layer="FIXTURE"):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


# Fixture blocks: origin = bottom-left of the fixture footprint, the side that goes
# against the wall is at the TOP (y = depth). Block names are what the Company Rules
# look for (e.g. a full bath must contain SINK, TOILET and SHOWER blocks).
def _blk_toilet(b):
    _rect(b, 0, 20, 20, 28)
    b.add_ellipse((10, 10), major_axis=(0, 9.5), ratio=0.75, dxfattribs={"layer": "FIXTURE"})


def _blk_sink(b):
    _rect(b, 0, 0, 24, 21)
    b.add_ellipse((12, 10), major_axis=(7, 0), ratio=0.7, dxfattribs={"layer": "FIXTURE"})


def _blk_shower(b):
    _rect(b, 0, 0, 36, 36)
    _rect(b, 2, 2, 34, 34)
    b.add_circle((18, 18), 1.5, dxfattribs={"layer": "FIXTURE"})
    b.add_line((2, 2), (34, 34), dxfattribs={"layer": "FIXTURE"})
    b.add_line((2, 34), (34, 2), dxfattribs={"layer": "FIXTURE"})


def _blk_appliance(b, w=27, d=28):
    _rect(b, 0, 0, w, d)
    b.add_circle((w / 2, d / 2 - 1), min(w, d) / 3, dxfattribs={"layer": "FIXTURE"})


def _blk_bed(w):
    def f(b):
        _rect(b, 0, 0, w, 80, "FURNITURE")
        b.add_line((0, 60), (w, 60), dxfattribs={"layer": "FURNITURE"})
        half = w / 2
        _rect(b, 4, 66, half - 3, 76, "FURNITURE")
        _rect(b, half + 3, 66, w - 4, 76, "FURNITURE")
    return f


def _blk_nightstand(b):
    _rect(b, 0, 0, 20, 18, "FURNITURE")


def _blk_range(b):
    _rect(b, 0, 0, 30, 25)
    for bx in (8, 22):
        for by in (7, 18):
            b.add_circle((bx, by), 4, dxfattribs={"layer": "FIXTURE"})


def _blk_kitchen_sink(b):
    _rect(b, 0, 0, 33, 22)
    _rect(b, 3, 3, 16, 19)
    _rect(b, 17, 3, 30, 19)


def _blk_ref(b):
    _rect(b, 0, 0, 36, 30)
    b.add_line((0, 0), (36, 30), dxfattribs={"layer": "FIXTURE"})


def _blk_island(b):
    _rect(b, 0, 0, 96, 42)


def _blk_dining(b):
    _rect(b, 12, 18, 84, 60, "FURNITURE")
    for k in range(3):
        b.add_circle((24 + k * 24, 8), 8, dxfattribs={"layer": "FURNITURE"})
        b.add_circle((24 + k * 24, 70), 8, dxfattribs={"layer": "FURNITURE"})


def _blk_desk(b):
    _rect(b, 0, 10, 60, 36, "FURNITURE")
    b.add_circle((30, 0), 10, dxfattribs={"layer": "FURNITURE"})


def _blk_bench(b):
    _rect(b, 0, 0, 60, 16, "FURNITURE")
    for k in range(1, 4):
        b.add_line((k * 15, 0), (k * 15, 16), dxfattribs={"layer": "FURNITURE"})


BLOCKS = {
    "TOILET": _blk_toilet, "SINK": _blk_sink, "SHOWER": _blk_shower,
    "WASHER": lambda b: _blk_appliance(b), "DRYER": lambda b: _blk_appliance(b),
    "BED_KING": _blk_bed(76), "BED_QUEEN": _blk_bed(60), "NIGHTSTAND": _blk_nightstand,
    "RANGE": _blk_range, "KITCHEN_SINK": _blk_kitchen_sink, "REFRIGERATOR": _blk_ref, "ISLAND": _blk_island,
    "DINING_TABLE": _blk_dining, "DESK": _blk_desk, "BENCH_LOCKERS": _blk_bench,
}


def _put(doc, msp, name, x, y, rotation=0.0):
    if name not in doc.blocks:
        blk = doc.blocks.new(name)
        BLOCKS[name](blk)
    msp.add_blockref(name, (x, y), dxfattribs={"rotation": rotation, "layer": "FIXTURE"})


def _draw(module_id: str, doc, msp, W: float, D: float) -> None:
    """W, D = minimum box in inches. Door wall at the bottom (y=0), back wall at y=D."""
    if module_id == "great_room":
        cx = W / 2
        _rect(msp, 24, D - 25, W - 24, D)                               # counter run on the back wall
        _put(doc, msp, "RANGE", 40, D - 25)
        _put(doc, msp, "KITCHEN_SINK", cx - 16.5, D - 23)
        _put(doc, msp, "REFRIGERATOR", W - 24 - 36, D - 30)
        _put(doc, msp, "ISLAND", cx - 48, D - 25 - 42 - 42)
        _put(doc, msp, "DINING_TABLE", cx - 48, max(0, D - 25 - 42 - 42 - 36 - 78))
    elif module_id == "master_bedroom":
        cx = W / 2
        _put(doc, msp, "BED_KING", cx - 38, D - 80)
        _put(doc, msp, "NIGHTSTAND", cx - 62, D - 18)
        _put(doc, msp, "NIGHTSTAND", cx + 42, D - 18)
    elif module_id == "bedroom":
        cx = W / 2
        _put(doc, msp, "BED_QUEEN", cx - 30, D - 80)
        _put(doc, msp, "NIGHTSTAND", cx - 52, D - 18)
    elif module_id == "master_bath":
        _rect(msp, 0, D - 22, 60, D)                                    # double vanity top
        _put(doc, msp, "SINK", 4, D - 21)
        _put(doc, msp, "SINK", 32, D - 21)
        _put(doc, msp, "SHOWER", W - 36, D - 36)
        _put(doc, msp, "TOILET", W - 28, 20, rotation=-90)              # on the right wall, front half
    elif module_id == "full_bath":
        _put(doc, msp, "SHOWER", 0, D - 36)
        _put(doc, msp, "TOILET", 41, D - 28)
        _put(doc, msp, "SINK", W - 24, D - 21)
    elif module_id == "half_bath":
        _put(doc, msp, "SINK", 0, D - 21)
        _put(doc, msp, "TOILET", W - 26, D - 28)
    elif module_id == "laundry_mud":
        _put(doc, msp, "WASHER", 0, D - 28)
        _put(doc, msp, "DRYER", 28, D - 28)
        _put(doc, msp, "BENCH_LOCKERS", 0, 0, rotation=0) if W >= 60 else None
    elif module_id == "master_wic":
        _rect(msp, 0, 0, 14, D, "FURNITURE")
        _rect(msp, W - 14, 0, W, D, "FURNITURE")
        msp.add_line((7, 0), (7, D), dxfattribs={"layer": "FURNITURE"})
        msp.add_line((W - 7, 0), (W - 7, D), dxfattribs={"layer": "FURNITURE"})
    elif module_id == "pantry":
        _rect(msp, 0, 0, 12, D)
        _rect(msp, 12, D - 12, W, D)
        _rect(msp, W - 12, 0, W, D - 12)
    elif module_id == "office":
        _put(doc, msp, "DESK", W / 2 - 30, D - 36)
        _rect(msp, 0, 0, 14, 48, "FURNITURE")                           # bookcase
    elif module_id == "flex":
        cx, cy = W / 2, D / 2
        _rect(msp, cx - 44, cy - 10, cx + 44, cy + 26, "FURNITURE")     # sectional
        _rect(msp, cx - 44, cy - 10, cx - 8, cy + 26, "FURNITURE")
        _rect(msp, cx - 20, cy - 40, cx + 20, cy - 20, "FURNITURE")     # coffee table


def create_placeholder_library(rb: Rulebook, overwrite: bool = False, directory: Path | None = None) -> list[Path]:
    directory = directory or MODULES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for m in rb.modules.values():
        if not m.dxf_file:
            continue
        path = directory / m.dxf_file
        if path.exists() and not overwrite:
            continue
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = 1
        for name, color in (("FIXTURE", 4), ("FURNITURE", 8)):
            doc.layers.add(name, color=color)
        msp = doc.modelspace()
        W, D = m.min_w * 12, m.min_d * 12
        _draw(m.id, doc, msp, W, D)
        doc.saveas(path)
        out.append(path)
    return out


# ---------------------------------------------------------------------------
# Fixture inventory (block names used in a module drawing)
# ---------------------------------------------------------------------------
FIXTURE_SYNONYMS = {
    "sink": ("SINK", "LAV", "VANITY", "BASIN"),
    "toilet": ("TOILET", "WC", "WATER_CLOSET", "WATERCLOSET"),
    "shower": ("SHOWER", "SHWR"),
    "tub": ("TUB", "BATHTUB"),
    "washer": ("WASHER",),
    "dryer": ("DRYER",),
}


@lru_cache(maxsize=128)
def _block_names(path_str: str, mtime: float) -> frozenset[str]:
    doc = ezdxf.readfile(path_str)
    names: set[str] = set()

    def walk(layout):
        for e in layout:
            if e.dxftype() == "INSERT":
                n = e.dxf.name.upper()
                names.add(n)
                if n in doc.blocks:
                    walk(doc.blocks[n])
    walk(doc.modelspace())
    return frozenset(names)


def module_fixtures(path: Path | None) -> set[str]:
    """Generic fixture names ('sink', 'toilet', 'shower'...) found in a module drawing."""
    if not path or not path.exists():
        return set()
    names = _block_names(str(path), path.stat().st_mtime)
    found = set()
    for generic, keys in FIXTURE_SYNONYMS.items():
        if any(k in n for n in names for k in keys):
            found.add(generic)
    return found


# ---------------------------------------------------------------------------
# Loading as primitives (feet, module-local coordinates)
# ---------------------------------------------------------------------------
def _entities(e):
    if e.dxftype() == "INSERT":
        for v in e.virtual_entities():
            yield from _entities(v)
    else:
        yield e


@lru_cache(maxsize=128)
def _load(path_str: str, mtime: float) -> tuple[tuple, ...]:
    doc = ezdxf.readfile(path_str)
    units = doc.header.get("$INSUNITS", 1)
    scale = {1: 1 / 12, 2: 1.0, 4: 1 / 304.8, 5: 1 / 30.48, 6: 1 / 0.3048}.get(units, 1 / 12)
    prims = []
    for top in doc.modelspace():
        for e in _entities(top):
            t = e.dxftype()
            layer = e.dxf.layer
            if t == "LINE":
                s, en = e.dxf.start, e.dxf.end
                prims.append(("line", layer, ((s.x * scale, s.y * scale), (en.x * scale, en.y * scale))))
            elif t == "LWPOLYLINE":
                pts = tuple((p[0] * scale, p[1] * scale) for p in e.get_points("xy"))
                prims.append(("poly", layer, (pts, bool(e.closed))))
            elif t == "CIRCLE":
                c = e.dxf.center
                prims.append(("circle", layer, ((c.x * scale, c.y * scale), e.dxf.radius * scale)))
            elif t == "ARC":
                c = e.dxf.center
                prims.append(("arc", layer, ((c.x * scale, c.y * scale), e.dxf.radius * scale,
                                             e.dxf.start_angle, e.dxf.end_angle)))
            elif t == "ELLIPSE":
                pts = tuple((p.x * scale, p.y * scale) for p in e.flattening(0.5))
                prims.append(("poly", layer, (pts, True)))
            elif t in ("TEXT", "MTEXT"):
                ins = e.dxf.insert
                txt = e.dxf.text if t == "TEXT" else e.text
                prims.append(("text", layer, ((ins.x * scale, ins.y * scale), txt, getattr(e.dxf, "height", 4) * scale)))
    return tuple(prims)


def load_primitives(path: Path | None) -> tuple[tuple, ...]:
    if not path or not path.exists():
        return ()
    return _load(str(path), path.stat().st_mtime)


# ---------------------------------------------------------------------------
# Placement transform
# ---------------------------------------------------------------------------
_BACK = {"S": "N", "N": "S", "W": "E", "E": "W"}
_LEFT = {"S": "W", "N": "E", "W": "N", "E": "S"}
_RIGHT = {"S": "E", "N": "W", "W": "S", "E": "N"}


def placement(space, door_side: str, box_w: float, box_d: float, anchor: str, ext_sides: list[str],
              ext_wall: float = 0.67, int_wall: float = 0.375) -> tuple[tuple[float, float], float]:
    """Return (insert point in feet, rotation degrees) for a module drawing."""
    x0, y0, x1, y1 = space.x0, space.y0, space.x1, space.y1
    if door_side == "S":
        theta, O, W, Dp = 0.0, (x0, y0), x1 - x0, y1 - y0
    elif door_side == "N":
        theta, O, W, Dp = 180.0, (x1, y1), x1 - x0, y1 - y0
    elif door_side == "W":
        theta, O, W, Dp = -90.0, (x0, y1), y1 - y0, x1 - x0
    else:
        theta, O, W, Dp = 90.0, (x1, y0), y1 - y0, x1 - x0

    def inset(side):
        return (ext_wall if side in ext_sides else int_wall / 2) + 0.08

    back, left, right = inset(_BACK[door_side]), inset(_LEFT[door_side]), inset(_RIGHT[door_side])
    if anchor == "back-left":
        lx, ly = left, Dp - box_d - back
    elif anchor == "back-right":
        lx, ly = W - box_w - right, Dp - box_d - back
    elif anchor == "center":
        lx, ly = (W - box_w) / 2, (Dp - box_d) / 2
    else:
        lx, ly = (W - box_w) / 2, Dp - box_d - back
    t = math.radians(theta)
    ix = O[0] + lx * math.cos(t) - ly * math.sin(t)
    iy = O[1] + lx * math.sin(t) + ly * math.cos(t)
    return (ix, iy), theta


def transform_point(p, insert, theta):
    t = math.radians(theta)
    return (insert[0] + p[0] * math.cos(t) - p[1] * math.sin(t), insert[1] + p[0] * math.sin(t) + p[1] * math.cos(t))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_library(rb: Rulebook) -> list[dict[str, Any]]:
    report = []
    for m in rb.modules.values():
        entry = {"module": m.id, "file": m.dxf_file, "status": "ok", "issues": []}
        if not m.dxf_file:
            entry["status"] = "no drawing"
            report.append(entry)
            continue
        path = m.dxf_path
        if not path or not path.exists():
            entry["status"] = "missing"
            entry["issues"].append(f"{m.dxf_file} not found in {MODULES_DIR}")
            report.append(entry)
            continue
        try:
            doc = ezdxf.readfile(path)
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "error"
            entry["issues"].append(f"cannot read: {exc}")
            report.append(entry)
            continue
        if doc.header.get("$INSUNITS", 0) != 1:
            entry["issues"].append("units are not inches ($INSUNITS should be 1)")
        W, D = m.min_w * 12, m.min_d * 12
        from ezdxf import bbox

        box = bbox.extents(doc.modelspace())
        if box.has_data:
            tol = 1.0
            if box.extmin.x < -tol or box.extmin.y < -tol or box.extmax.x > W + tol or box.extmax.y > D + tol:
                entry["issues"].append(
                    f"drawing extents {box.extmin.x:.0f},{box.extmin.y:.0f} .. {box.extmax.x:.0f},{box.extmax.y:.0f} in "
                    f"exceed the minimum room box 0,0 .. {W:.0f},{D:.0f} in")
        else:
            entry["issues"].append("drawing is empty")
        layers = {e.dxf.layer for e in doc.modelspace()}
        bad = layers - ALLOWED_LAYERS
        if bad:
            entry["issues"].append(f"unexpected layers: {', '.join(sorted(bad))}")
        if entry["issues"]:
            entry["status"] = "warning"
        report.append(entry)
    return report
