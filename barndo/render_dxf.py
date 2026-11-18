"""Write a layout to a layered DXF (inches) that opens in AutoCAD / BricsCAD /
DraftSight, with optional DWG conversion through the ODA File Converter."""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import ezdxf
from ezdxf.addons import Importer
from ezdxf.enums import TextEntityAlignment

from .config import COMPANY_NAME, ODA_CONVERTER
from .layout import Layout, clear_dims, fmt_ft
from .render_svg import door_symbol, fixture_placements, wall_geometry
from .rules import Rulebook

IN = 12.0  # feet -> inches

LAYERS = {
    "A-WALL": 7, "A-WALL-PATT": 8, "A-DOOR": 2, "A-GLAZ": 4, "A-OVHD": 6, "A-AREA": 9, "A-AREA-IDEN": 7,
    "A-FURN": 8, "A-FLOR-FIXT": 4, "S-COLS": 1, "A-DIMS": 3, "A-PORCH": 30, "A-ANNO-TTLB": 7,
}


def _pt(p):
    return (p[0] * IN, p[1] * IN)


def write_dxf(lay: Layout, rb: Rulebook, path: Path | str, customer: str = "") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 1
    doc.header["$LUNITS"] = 4  # architectural
    doc.header["$MEASUREMENT"] = 0
    for name, color in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    doc.layers.get("A-PORCH").dxf.linetype = "DASHED"
    doc.layers.get("A-OVHD").dxf.linetype = "HIDDEN"
    msp = doc.modelspace()
    L, D = lay.length, lay.width
    ext = rb.b("ext_wall")

    # --- walls --------------------------------------------------------------
    walls = wall_geometry(lay, rb)
    polys = [walls] if walls.geom_type == "Polygon" else [g for g in getattr(walls, "geoms", []) if g.geom_type == "Polygon"]
    for poly in polys:
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL-PATT"})
        hatch.paths.add_polyline_path([_pt(c) for c in poly.exterior.coords], is_closed=True, flags=1)
        for ring in poly.interiors:
            hatch.paths.add_polyline_path([_pt(c) for c in ring.coords], is_closed=True, flags=16)
        for ring in [poly.exterior, *poly.interiors]:
            msp.add_lwpolyline([_pt(c) for c in ring.coords], close=True, dxfattribs={"layer": "A-WALL"})

    # --- rooms: boundary + label ----------------------------------------------
    for s in lay.spaces:
        msp.add_lwpolyline([_pt(p) for p in ((s.x0, s.y0), (s.x1, s.y0), (s.x1, s.y1), (s.x0, s.y1))], close=True,
                           dxfattribs={"layer": "A-AREA"})
        if s.kind in ("link", "shop_link"):
            continue
        name = "HALL" if s.kind == "hall" else s.name.upper()
        cw, ch = clear_dims(lay, s, ext, rb.b("int_wall"))
        rot = 90 if (s.h > s.w * 1.6 and s.w < 8) else 0
        cy = s.cy if s.kind != "great_room" else s.y0 + min(s.h * 0.32, 11)
        h1 = 9 if min(s.w, s.h) >= 7 else 6
        lines = [name] if s.kind == "hall" else [name, f"{fmt_ft(cw)} x {fmt_ft(ch)}", f"{round(s.area)} SF"]
        for k, txt in enumerate(lines):
            off = (len(lines) - 1) / 2 * h1 * 1.6 - k * h1 * 1.6
            if rot:
                pos = (s.cx * IN - off, cy * IN)
            else:
                pos = (s.cx * IN, cy * IN + off)
            t = msp.add_text(txt, height=h1 if k == 0 else h1 * 0.75,
                             dxfattribs={"layer": "A-AREA-IDEN", "rotation": rot, "style": "OpenSans"})
            t.set_placement(pos, align=TextEntityAlignment.MIDDLE_CENTER)

    # --- fixtures (module blocks) ----------------------------------------------
    importer = None
    defined: set[str] = set()
    for s, m, ins, theta, _prims in fixture_placements(lay, rb):
        bname = f"MOD_{m.id.upper()}"
        if bname not in defined:
            src = ezdxf.readfile(m.dxf_path)
            importer = Importer(src, doc)
            block = doc.blocks.new(bname)
            importer.import_entities(src.modelspace(), target_layout=block)
            importer.finalize()
            defined.add(bname)
        msp.add_blockref(bname, _pt(ins), dxfattribs={"rotation": theta, "layer": "A-FURN"})

    # --- doors ------------------------------------------------------------------
    for d in lay.doors:
        if d.kind == "overhead":
            if d.axis == "x":
                yy = d.y + (ext if abs(d.y) < 1e-6 else -ext)
                inner = yy + (1.2 if abs(d.y) < 1e-6 else -1.2)
                pts = [(d.x - d.width / 2, yy), (d.x + d.width / 2, yy), (d.x + d.width / 2, inner), (d.x - d.width / 2, inner)]
                tp = (d.x, inner + (1.5 if abs(d.y) < 1e-6 else -1.5))
                rot = 0
            else:
                xx = d.x - ext if abs(d.x - L) < 1e-6 else d.x + ext
                inner = xx - 1.2 if abs(d.x - L) < 1e-6 else xx + 1.2
                pts = [(xx, d.y - d.width / 2), (xx, d.y + d.width / 2), (inner, d.y + d.width / 2), (inner, d.y - d.width / 2)]
                tp = (inner - 1.5 if abs(d.x - L) < 1e-6 else inner + 1.5, d.y)
                rot = 90
            msp.add_lwpolyline([_pt(p) for p in pts], close=True, dxfattribs={"layer": "A-OVHD"})
            t = msp.add_text(f"{fmt_ft(d.width)} OVERHEAD DOOR", height=6, dxfattribs={"layer": "A-DOOR", "rotation": rot})
            t.set_placement(_pt(tp), align=TextEntityAlignment.MIDDLE_CENTER)
            continue
        hinge, leaf, closed = door_symbol(d, ext, L, D)
        msp.add_line(_pt(hinge), _pt(leaf), dxfattribs={"layer": "A-DOOR"})
        a_leaf = math.degrees(math.atan2(leaf[1] - hinge[1], leaf[0] - hinge[0])) % 360
        a_closed = math.degrees(math.atan2(closed[1] - hinge[1], closed[0] - hinge[0])) % 360
        if round((a_closed - a_leaf) % 360) == 90:
            start, end = a_leaf, a_closed
        else:
            start, end = a_closed, a_leaf
        msp.add_arc(_pt(hinge), d.width * IN, start, end, dxfattribs={"layer": "A-DOOR"})

    # --- windows -----------------------------------------------------------------
    for w in lay.windows:
        if w.axis == "x":
            y0, y1 = (0, ext) if abs(w.y) < 1e-6 else (D - ext, D)
            pts = [(w.x - w.width / 2, y0), (w.x + w.width / 2, y0), (w.x + w.width / 2, y1), (w.x - w.width / 2, y1)]
            msp.add_line(_pt((w.x - w.width / 2, (y0 + y1) / 2)), _pt((w.x + w.width / 2, (y0 + y1) / 2)), dxfattribs={"layer": "A-GLAZ"})
        else:
            x0, x1 = (0, ext) if abs(w.x) < 1e-6 else (L - ext, L)
            pts = [(x0, w.y - w.width / 2), (x1, w.y - w.width / 2), (x1, w.y + w.width / 2), (x0, w.y + w.width / 2)]
            msp.add_line(_pt(((x0 + x1) / 2, w.y - w.width / 2)), _pt(((x0 + x1) / 2, w.y + w.width / 2)), dxfattribs={"layer": "A-GLAZ"})
        msp.add_lwpolyline([_pt(p) for p in pts], close=True, dxfattribs={"layer": "A-GLAZ"})

    # --- posts -------------------------------------------------------------------
    ps = rb.b("post_size")
    for x, y in lay.posts:
        px = min(max(x, ps / 2), L - ps / 2)
        py = min(max(y, ps / 2), D - ps / 2)
        pts = [_pt(p) for p in ((px - ps / 2, py - ps / 2), (px + ps / 2, py - ps / 2), (px + ps / 2, py + ps / 2), (px - ps / 2, py + ps / 2))]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-COLS"})
        h = msp.add_hatch(color=1, dxfattribs={"layer": "S-COLS"})
        h.paths.add_polyline_path(pts, is_closed=True)

    # --- porches -----------------------------------------------------------------
    for x0, y0, x1, y1 in lay.porches:
        msp.add_lwpolyline([_pt(p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))], close=True, dxfattribs={"layer": "A-PORCH"})
        t = msp.add_text("COVERED PORCH", height=9, dxfattribs={"layer": "A-AREA-IDEN"})
        t.set_placement(_pt(((x0 + x1) / 2, (y0 + y1) / 2)), align=TextEntityAlignment.MIDDLE_CENTER)

    # --- dimensions -------------------------------------------------------------------
    miny = min([0.0] + [p[1] for p in lay.porches])
    maxy = max([D] + [p[3] for p in lay.porches])
    ov = {"dimtxt": 9, "dimasz": 6, "dimexo": 3, "dimexe": 3, "dimgap": 2, "dimtad": 1, "dimtsz": 4}
    dim = msp.add_linear_dim(base=_pt((0, maxy + 4)), p1=_pt((0, D)), p2=_pt((L, D)), angle=0, text=fmt_ft(L),
                             dimstyle="EZDXF", override=ov, dxfattribs={"layer": "A-DIMS"})
    dim.render()
    dim = msp.add_linear_dim(base=_pt((-4, 0)), p1=_pt((0, 0)), p2=_pt((0, D)), angle=90, text=fmt_ft(D),
                             dimstyle="EZDXF", override=ov, dxfattribs={"layer": "A-DIMS"})
    dim.render()
    cuts = sorted({0.0, L} | {round(s.x0, 3) for s in lay.spaces if s.kind in ("great_room", "shop")}
                  | {round(s.x1, 3) for s in lay.spaces if s.kind in ("great_room", "shop")})
    for a, b in zip(cuts, cuts[1:]):
        if b - a > 1:
            dim = msp.add_linear_dim(base=_pt((0, miny - 4)), p1=_pt((a, 0)), p2=_pt((b, 0)), angle=0, text=fmt_ft(b - a),
                                     dimstyle="EZDXF", override=ov, dxfattribs={"layer": "A-DIMS"})
            dim.render()

    # --- title block + room schedule ------------------------------------------------
    _title_block(msp, lay, rb, customer, miny - 10)
    doc.saveas(path)
    return path


def _title_block(msp, lay: Layout, rb: Rulebook, customer: str, top_y: float) -> None:
    L = lay.length
    width = max(L, 60.0)
    rows = [s for s in lay.spaces if s.kind in rb.modules]
    height = max(16.0, 5 + 1.45 * (len(rows) + 2))
    x0, y1 = 0.0, top_y
    y0 = y1 - height
    msp.add_lwpolyline([_pt(p) for p in ((x0, y0), (x0 + width, y0), (x0 + width, y1), (x0, y1))], close=True,
                       dxfattribs={"layer": "A-ANNO-TTLB"})
    msp.add_line(_pt((x0 + width * 0.55, y0)), _pt((x0 + width * 0.55, y1)), dxfattribs={"layer": "A-ANNO-TTLB"})

    def txt(s, x, y, h=7, bold=False):
        t = msp.add_text(s, height=h * (1.25 if bold else 1), dxfattribs={"layer": "A-ANNO-TTLB"})
        t.set_placement(_pt((x, y)), align=TextEntityAlignment.LEFT)

    m = lay.metrics
    y = y1 - 2
    txt(COMPANY_NAME.upper(), x0 + 1.5, y, 12, True)
    y -= 2.4
    txt("CONCEPT FLOOR PLAN - NOT FOR CONSTRUCTION", x0 + 1.5, y, 8)
    y -= 1.8
    for line in [
        f"Customer: {customer or '-'}",
        f"Plan ID: {lay.id}    Date: {date.today().isoformat()}",
        f"Building: {m.get('footprint', '')}   Living: {m.get('living_sqft', '')} SF   Shop: {m.get('shop_sqft', 0)} SF   Porch: {m.get('porch_sqft', 0)} SF",
        f"{m.get('bedrooms')} bed / {m.get('full_baths')} bath" + (f" / {m.get('half_baths')} half" if m.get('half_baths') else ""),
        f"Budget estimate: ${lay.estimate.get('total', 0):,.0f}  (placeholder rates)",
        f"Post spacing {rb.b('bay_spacing'):g} ft.  Ext. walls {fmt_ft(rb.b('ext_wall'))}.  Engineer of record to verify structure.",
    ]:
        txt(line, x0 + 1.5, y, 7)
        y -= 1.5
    # schedule
    sx = x0 + width * 0.55 + 1.5
    y = y1 - 2
    txt("ROOM SCHEDULE", sx, y, 9, True)
    y -= 1.9
    for s in rows:
        cw, ch = clear_dims(lay, s, rb.b("ext_wall"), rb.b("int_wall"))
        txt(f"{s.name:<28} {fmt_ft(cw)} x {fmt_ft(ch)}   {round(s.area)} SF", sx, y, 6.5)
        y -= 1.4


def oda_available() -> bool:
    return bool(ODA_CONVERTER and Path(ODA_CONVERTER).exists()) or bool(shutil.which("ODAFileConverter"))


def convert_to_dwg(dxf_path: Path | str, out_dir: Path | str | None = None, version: str = "ACAD2018") -> Path:
    """Convert a DXF to DWG with the free ODA File Converter.

    Install it from opendesign.com and set ODA_FILE_CONVERTER to the executable path.
    """
    exe = ODA_CONVERTER or shutil.which("ODAFileConverter")
    if not exe:
        raise RuntimeError("DWG export needs the free ODA File Converter. Install it and set ODA_FILE_CONVERTER.")
    dxf_path = Path(dxf_path)
    out_dir = Path(out_dir) if out_dir else dxf_path.parent
    with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
        shutil.copy(dxf_path, Path(tin) / dxf_path.name)
        subprocess.run([exe, tin, tout, version, "DWG", "0", "1", "*.DXF"], check=True, timeout=120,
                       capture_output=True)
        produced = list(Path(tout).glob("*.dwg")) + list(Path(tout).glob("*.DWG"))
        if not produced:
            raise RuntimeError("ODA File Converter did not produce a DWG file.")
        target = out_dir / (dxf_path.stem + ".dwg")
        shutil.copy(produced[0], target)
        return target
