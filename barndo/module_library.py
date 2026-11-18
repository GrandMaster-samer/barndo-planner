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
* Allowed entities: LINE, LWPOLYLINE, CIRCLE, ARC, TEXT (blocks are exploded).

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


def _toilet(msp, cx, back_y):
    _rect(msp, cx - 10, back_y - 8, cx + 10, back_y)
    msp.add_ellipse((cx, back_y - 18), major_axis=(0, 9), ratio=0.75, dxfattribs={"layer": "FIXTURE"})


def _draw(module_id: str, msp, W: float, D: float) -> None:
    """W, D = min box in inches."""
    if module_id == "great_room":
        # kitchen run on the back wall, island, dining table
        _rect(msp, 24, D - 25, W - 24, D)
        _rect(msp, W - 24 - 36, D - 30, W - 24, D)                      # refrigerator
        msp.add_text("REF", height=4, dxfattribs={"layer": "FIXTURE", "insert": (W - 24 - 30, D - 18)})
        cx = W / 2
        _rect(msp, cx - 15, D - 22, cx + 15, D - 4)                       # sink
        _rect(msp, 36, D - 25, 66, D)                                     # range
        for bx in (43, 59):
            for by in (D - 19, D - 7):
                msp.add_circle((bx, by), 4, dxfattribs={"layer": "FIXTURE"})
        _rect(msp, cx - 48, D - 25 - 42 - 42, cx + 48, D - 25 - 42)       # island 8' x 3.5'
        ty = D - 25 - 42 - 42 - 48 - 42
        _rect(msp, cx - 36, ty, cx + 36, ty + 42, "FURNITURE")            # dining table
        for k in range(3):
            x = cx - 24 + k * 24
            msp.add_circle((x, ty - 10), 8, dxfattribs={"layer": "FURNITURE"})
            msp.add_circle((x, ty + 52), 8, dxfattribs={"layer": "FURNITURE"})
    elif module_id == "master_bedroom":
        cx = W / 2
        _rect(msp, cx - 38, D - 80, cx + 38, D, "FURNITURE")             # king bed
        msp.add_line((cx - 38, D - 60), (cx + 38, D - 60), dxfattribs={"layer": "FURNITURE"})
        _rect(msp, cx - 32, D - 14, cx - 4, D - 4, "FURNITURE")
        _rect(msp, cx + 4, D - 14, cx + 32, D - 4, "FURNITURE")
        _rect(msp, cx - 62, D - 20, cx - 42, D, "FURNITURE")             # nightstands
        _rect(msp, cx + 42, D - 20, cx + 62, D, "FURNITURE")
    elif module_id == "bedroom":
        cx = W / 2
        _rect(msp, cx - 30, D - 80, cx + 30, D, "FURNITURE")             # queen bed
        msp.add_line((cx - 30, D - 62), (cx + 30, D - 62), dxfattribs={"layer": "FURNITURE"})
        _rect(msp, cx - 26, D - 14, cx - 3, D - 4, "FURNITURE")
        _rect(msp, cx + 3, D - 14, cx + 26, D - 4, "FURNITURE")
        _rect(msp, cx - 52, D - 18, cx - 34, D, "FURNITURE")
    elif module_id == "master_bath":
        _rect(msp, 0, D - 22, 60, D)                                      # double vanity
        for x in (15, 45):
            msp.add_ellipse((x, D - 11), major_axis=(7, 0), ratio=0.7, dxfattribs={"layer": "FIXTURE"})
        _toilet(msp, W - 12, D)
        _rect(msp, 0, 0 + 2, 36, 38)                                      # shower
        msp.add_line((0, 2), (36, 38), dxfattribs={"layer": "FIXTURE"})
        msp.add_line((0, 38), (36, 2), dxfattribs={"layer": "FIXTURE"})
    elif module_id == "full_bath":
        _rect(msp, 0, D - 30, 60, D)                                      # tub
        _rect(msp, 4, D - 26, 56, D - 4)
        _toilet(msp, W - 12, D)
        _rect(msp, W - 22, 0, W, 20)                                      # vanity
        msp.add_ellipse((W - 11, 10), major_axis=(0, 6), ratio=0.7, dxfattribs={"layer": "FIXTURE"})
    elif module_id == "half_bath":
        _toilet(msp, W - 14, D)
        _rect(msp, 0, D - 18, 16, D)
        msp.add_circle((8, D - 9), 5, dxfattribs={"layer": "FIXTURE"})
    elif module_id == "master_wic":
        _rect(msp, 0, 0, 14, D, "FURNITURE")
        _rect(msp, W - 14, 0, W, D, "FURNITURE")
        msp.add_line((7, 0), (7, D), dxfattribs={"layer": "FURNITURE"})
        msp.add_line((W - 7, 0), (W - 7, D), dxfattribs={"layer": "FURNITURE"})
    elif module_id == "laundry":
        for x0 in (0, 28):
            _rect(msp, x0, D - 28, x0 + 27, D)
            msp.add_circle((x0 + 13.5, D - 15), 9, dxfattribs={"layer": "FIXTURE"})
        _rect(msp, 0, D - 26, W, D, "FIXTURE") if W >= 72 else None
    elif module_id == "mudroom":
        _rect(msp, 0, D - 18, W, D, "FURNITURE")                          # bench + lockers
        for k in range(1, int(W // 15)):
            msp.add_line((k * 15, D - 18), (k * 15, D), dxfattribs={"layer": "FURNITURE"})
    elif module_id == "pantry":
        _rect(msp, 0, 0, 12, D)
        _rect(msp, 12, D - 12, W, D)
        _rect(msp, W - 12, 0, W, D - 12)
    elif module_id == "office":
        cx = W / 2
        _rect(msp, cx - 30, D - 26, cx + 30, D, "FURNITURE")              # desk
        msp.add_circle((cx, D - 40), 10, dxfattribs={"layer": "FURNITURE"})
        _rect(msp, 0, 0, 14, 48, "FURNITURE")                             # bookcase
    elif module_id == "flex":
        cx, cy = W / 2, D / 2
        _rect(msp, cx - 44, cy - 10, cx + 44, cy + 26, "FURNITURE")       # sectional
        _rect(msp, cx - 44, cy - 10, cx - 8, cy + 26, "FURNITURE")
        _rect(msp, cx - 20, cy - 40, cx + 20, cy - 20, "FURNITURE")       # coffee table


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
        _draw(m.id, msp, W, D)
        doc.saveas(path)
        out.append(path)
    return out


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
