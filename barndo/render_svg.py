"""Render a layout as an SVG floor plan (used by the web app and proposals)."""
from __future__ import annotations

import math
from html import escape

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .layout import Layout, Space, clear_dims, fmt_ft
from .module_library import load_primitives, placement, transform_point
from .rules import Rulebook
from .walls import interior_walls

CIRC_FILL = "#FBFAF7"
SHOP_FILL = "#ECEAE4"
WALL = "#2B2622"


# ---------------------------------------------------------------------------
# Shared geometry (also used by the DXF writer)
# ---------------------------------------------------------------------------
def wall_geometry(lay: Layout, rb: Rulebook):
    """Return a shapely geometry of all walls with door/window openings cut out."""
    ext = rb.b("ext_wall")
    t_int = rb.b("int_wall")
    t_shop = rb.b("shop_wall")
    L, D = lay.length, lay.width
    parts = [box(0, 0, L, D).difference(box(ext, ext, L - ext, D - ext))]
    for axis, fixed, lo, hi, kind in interior_walls(lay):
        t = t_shop if kind == "shop" else t_int
        if axis == "x":
            parts.append(box(lo - t / 2, fixed - t / 2, hi + t / 2, fixed + t / 2))
        else:
            parts.append(box(fixed - t / 2, lo - t / 2, fixed + t / 2, hi + t / 2))
    walls = unary_union(parts).intersection(box(0, 0, L, D))
    cuts = []
    for d in lay.doors:
        cuts.append(_opening_box(lay, d.x, d.y, d.axis, d.width, ext, max(t_int, t_shop)))
    for w in lay.windows:
        cuts.append(_opening_box(lay, w.x, w.y, w.axis, w.width, ext, t_int))
    if cuts:
        walls = walls.difference(unary_union(cuts))
    return walls


def _opening_box(lay: Layout, x, y, axis, width, ext, t):
    L, D = lay.length, lay.width
    if axis == "x":
        if abs(y) < 1e-6:
            return box(x - width / 2, -0.1, x + width / 2, ext + 0.1)
        if abs(y - D) < 1e-6:
            return box(x - width / 2, D - ext - 0.1, x + width / 2, D + 0.1)
        return box(x - width / 2, y - t / 2 - 0.1, x + width / 2, y + t / 2 + 0.1)
    if abs(x) < 1e-6:
        return box(-0.1, y - width / 2, ext + 0.1, y + width / 2)
    if abs(x - L) < 1e-6:
        return box(L - ext - 0.1, y - width / 2, L + 0.1, y + width / 2)
    return box(x - t / 2 - 0.1, y - width / 2, x + t / 2 + 0.1, y + width / 2)


def door_symbol(d, ext: float, L: float, D: float):
    """Return (hinge, leaf_end, closed_end) in feet for a swing door."""
    off = 0.0
    if d.wall == "ext":
        # swing from the inside face of the exterior wall
        if d.axis == "x":
            off = ext if abs(d.y) < 1e-6 else -ext
        else:
            off = ext if abs(d.x) < 1e-6 else -ext
    if d.axis == "x":
        cy = d.y + off
        hx = d.x + d.hinge * d.width / 2
        return (hx, cy), (hx, cy + d.into * d.width), (d.x - d.hinge * d.width / 2, cy)
    cx = d.x + off
    hy = d.y + d.hinge * d.width / 2
    return (cx, hy), (cx + d.into * d.width, hy), (cx, d.y - d.hinge * d.width / 2)


def fixture_placements(lay: Layout, rb: Rulebook):
    """Yield (space, module, insert, theta, primitives) for rooms that have a drawing."""
    for s in lay.spaces:
        if s.kind not in rb.modules or not s.door_side:
            continue
        m = rb.m(s.kind)
        prims = load_primitives(m.dxf_path)
        if not prims:
            continue
        ins, theta = placement(s, s.door_side, m.min_w, m.min_d, m.fixture_anchor, lay.exterior_sides(s),
                               rb.b("ext_wall"), rb.b("int_wall"))
        yield s, m, ins, theta, prims


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
class _Canvas:
    def __init__(self, minx, miny, maxx, maxy, scale, pad):
        self.minx, self.miny, self.maxx, self.maxy = minx, miny, maxx, maxy
        self.s, self.pad = scale, pad
        self.out: list[str] = []

    def X(self, x):
        return round((x - self.minx) * self.s + self.pad, 2)

    def Y(self, y):
        return round((self.maxy - y) * self.s + self.pad, 2)

    @property
    def width(self):
        return round((self.maxx - self.minx) * self.s + 2 * self.pad, 1)

    @property
    def height(self):
        return round((self.maxy - self.miny) * self.s + 2 * self.pad, 1)

    def add(self, el: str):
        self.out.append(el)

    def rect(self, x0, y0, x1, y1, **attrs):
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<rect x="{self.X(x0)}" y="{self.Y(y1)}" width="{round((x1 - x0) * self.s, 2)}" '
                 f'height="{round((y1 - y0) * self.s, 2)}" {a}/>')

    def line(self, p, q, **attrs):
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.add(f'<line x1="{self.X(p[0])}" y1="{self.Y(p[1])}" x2="{self.X(q[0])}" y2="{self.Y(q[1])}" {a}/>')

    def text(self, x, y, txt, size=11, weight="normal", anchor="middle", fill="#3a332c", rotate=0, cls=""):
        tr = f' transform="rotate({rotate} {self.X(x)} {self.Y(y)})"' if rotate else ""
        c = f' class="{cls}"' if cls else ""
        self.add(f'<text x="{self.X(x)}" y="{self.Y(y)}" font-size="{size}" font-weight="{weight}" '
                 f'text-anchor="{anchor}" dominant-baseline="middle" fill="{fill}"{tr}{c}>{escape(txt)}</text>')

    def path_from_geom(self, geom, **attrs):
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
        d = []
        for p in polys:
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            for ring in [p.exterior, *p.interiors]:
                pts = list(ring.coords)
                d.append("M" + " L".join(f"{self.X(x)},{self.Y(y)}" for x, y in pts) + " Z")
        if d:
            self.add(f'<path d="{" ".join(d)}" fill-rule="evenodd" {a}/>')


def render_svg(lay: Layout, rb: Rulebook, scale: float = 11.0, show_fixtures: bool = True,
               show_dims: bool = True, show_posts: bool = True, compact: bool = False) -> str:
    L, D = lay.length, lay.width
    ext = rb.b("ext_wall")
    miny = min([0.0] + [p[1] for p in lay.porches])
    maxy = max([D] + [p[3] for p in lay.porches])
    dim_off = 0 if (compact or not show_dims) else 7
    pad = 14 if compact else 18
    cv = _Canvas(-dim_off, miny - dim_off, L + (2 if compact else 4), maxy + dim_off, scale, pad)
    font = max(7.0, min(12.0, scale * 0.95))

    # porches
    for x0, y0, x1, y1 in lay.porches:
        cv.rect(x0, y0, x1, y1, fill="#F7F3EA", stroke="#9C8F7E", stroke_width=1, stroke_dasharray="5 4")
        cv.text((x0 + x1) / 2, (y0 + y1) / 2, "COVERED PORCH", size=font * 0.85, fill="#8b7d6b", weight="600")

    # room fills
    for s in lay.spaces:
        if s.kind == "shop":
            fill = SHOP_FILL
        elif s.kind in ("hall", "link", "shop_link"):
            fill = CIRC_FILL
        else:
            fill = rb.m(s.kind).color if s.kind in rb.modules else "#EEE"
        cv.rect(s.x0, s.y0, s.x1, s.y1, fill=fill, stroke="none")

    # fixtures
    if show_fixtures:
        for s, m, ins, theta, prims in fixture_placements(lay, rb):
            for kind, layer, data in prims:
                col = "#7b8a93" if layer == "FIXTURE" else "#a39787"
                if kind == "line":
                    p, q = (transform_point(pt, ins, theta) for pt in data)
                    cv.line(p, q, stroke=col, stroke_width=0.8)
                elif kind == "poly":
                    pts, closed = data
                    tp = [transform_point(pt, ins, theta) for pt in pts]
                    path = " L".join(f"{cv.X(x)},{cv.Y(y)}" for x, y in tp)
                    cv.add(f'<path d="M{path}{" Z" if closed else ""}" fill="none" stroke="{col}" stroke-width="0.8"/>')
                elif kind == "circle":
                    c, r = data
                    cc = transform_point(c, ins, theta)
                    cv.add(f'<circle cx="{cv.X(cc[0])}" cy="{cv.Y(cc[1])}" r="{round(r * cv.s, 2)}" fill="none" '
                           f'stroke="{col}" stroke-width="0.8"/>')
                elif kind == "arc":
                    c, r, a0, a1 = data
                    pts = []
                    span = (a1 - a0) % 360 or 360
                    for k in range(17):
                        a = math.radians(a0 + span * k / 16)
                        pts.append(transform_point((c[0] + r * math.cos(a), c[1] + r * math.sin(a)), ins, theta))
                    path = " L".join(f"{cv.X(x)},{cv.Y(y)}" for x, y in pts)
                    cv.add(f'<path d="M{path}" fill="none" stroke="{col}" stroke-width="0.8"/>')

    # walls
    walls = wall_geometry(lay, rb)
    cv.path_from_geom(walls, fill=WALL, stroke=WALL, stroke_width=0.4)

    # windows
    for w in lay.windows:
        if w.axis == "x":
            y0, y1 = (0, ext) if abs(w.y) < 1e-6 else (D - ext, D)
            cv.rect(w.x - w.width / 2, y0, w.x + w.width / 2, y1, fill="#FFFFFF", stroke=WALL, stroke_width=0.9)
            cv.line((w.x - w.width / 2, (y0 + y1) / 2), (w.x + w.width / 2, (y0 + y1) / 2), stroke="#4a90b8", stroke_width=1.1)
        else:
            x0, x1 = (0, ext) if abs(w.x) < 1e-6 else (L - ext, L)
            cv.rect(x0, w.y - w.width / 2, x1, w.y + w.width / 2, fill="#FFFFFF", stroke=WALL, stroke_width=0.9)
            cv.line(((x0 + x1) / 2, w.y - w.width / 2), ((x0 + x1) / 2, w.y + w.width / 2), stroke="#4a90b8", stroke_width=1.1)

    # doors
    for d in lay.doors:
        if d.kind == "overhead":
            if d.axis == "x":
                yy = d.y + (ext if abs(d.y) < 1e-6 else -ext)
                inner = yy + (1.2 if abs(d.y) < 1e-6 else -1.2)
                cv.rect(d.x - d.width / 2, min(yy, inner), d.x + d.width / 2, max(yy, inner), fill="none",
                        stroke="#555", stroke_width=1, stroke_dasharray="4 3")
                cv.text(d.x, inner + (1.6 if abs(d.y) < 1e-6 else -1.6), f"{fmt_ft(d.width)} OH DOOR", size=font * 0.8, fill="#555")
            else:
                xx = d.x - ext if abs(d.x - L) < 1e-6 else d.x + ext
                inner = xx - 1.2 if abs(d.x - L) < 1e-6 else xx + 1.2
                cv.rect(min(xx, inner), d.y - d.width / 2, max(xx, inner), d.y + d.width / 2, fill="none",
                        stroke="#555", stroke_width=1, stroke_dasharray="4 3")
                cv.text(inner - 1.8, d.y, f"{fmt_ft(d.width)} OH", size=font * 0.8, fill="#555", rotate=-90)
            continue
        hinge, leaf, closed = door_symbol(d, ext, L, D)
        cv.line(hinge, leaf, stroke="#3d342c", stroke_width=1.3)
        r = d.width * cv.s
        sweep = _sweep(hinge, leaf, closed)
        cv.add(f'<path d="M{cv.X(leaf[0])},{cv.Y(leaf[1])} A{r},{r} 0 0 {sweep} {cv.X(closed[0])},{cv.Y(closed[1])}" '
               f'fill="none" stroke="#3d342c" stroke-width="0.7" stroke-dasharray="2 2"/>')

    # posts
    if show_posts:
        ps = rb.b("post_size")
        for x, y in lay.posts:
            px = min(max(x, ps / 2), L - ps / 2)
            py = min(max(y, ps / 2), D - ps / 2)
            cv.rect(px - ps / 2, py - ps / 2, px + ps / 2, py + ps / 2, fill="#8B5A2B", stroke="none")

    # labels
    for s in lay.spaces:
        if s.kind in ("link", "shop_link"):
            continue
        if s.kind == "hall":
            if s.w >= s.h:
                cv.text(s.cx, s.cy, "HALL", size=font * 0.75, fill="#9a8f80", weight="600")
            else:
                cv.text(s.cx, s.cy, "HALL", size=font * 0.75, fill="#9a8f80", weight="600", rotate=-90)
            continue
        cw, ch = clear_dims(lay, s, rb.b("ext_wall"), rb.b("int_wall"))
        small = min(s.w, s.h) < 7
        size = font * (0.78 if small else 1.0)
        name = s.name.upper() if s.kind != "great_room" else "KITCHEN / DINING / LIVING"
        rot = -90 if (s.h > s.w * 1.6 and s.w < 8) else 0
        ly = s.cy if s.kind != "great_room" else s.y0 + min(s.h * 0.32, 11)
        if s.kind == "shop":
            ly = s.cy
        if rot:
            cv.text(s.cx - size / cv.s * 0.6, ly, name, size=size, weight="700", rotate=rot)
            cv.text(s.cx + size / cv.s * 0.75, ly, f"{fmt_ft(cw)} x {fmt_ft(ch)}", size=size * 0.85, rotate=rot, fill="#6b6157")
        else:
            cv.text(s.cx, ly + size / cv.s * 0.65, name, size=size, weight="700")
            cv.text(s.cx, ly - size / cv.s * 0.7, f"{fmt_ft(cw)} x {fmt_ft(ch)}", size=size * 0.85, fill="#6b6157")

    # dimensions
    if show_dims and not compact:
        _dim(cv, (0, maxy + 3.5), (L, maxy + 3.5), fmt_ft(L), font)
        _dim(cv, (-3.5, 0), (-3.5, D), fmt_ft(D), font, vertical=True)
        # block widths along the bottom
        cuts = sorted({0.0, L, lay.living_length if lay.shop_side == "right" else lay.shop_length} |
                      {round(s.x0, 3) for s in lay.spaces if s.kind in ("great_room", "shop")} |
                      {round(s.x1, 3) for s in lay.spaces if s.kind in ("great_room", "shop")})
        yb = miny - 3.5
        for a, b in zip(cuts, cuts[1:]):
            if b - a > 1:
                _dim(cv, (a, yb), (b, yb), fmt_ft(b - a), font * 0.9)

    body = "\n".join(cv.out)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cv.width} {cv.height}" '
            f'width="{cv.width}" height="{cv.height}" font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">'
            f'<rect width="100%" height="100%" fill="#FFFFFF"/>{body}</svg>')


def _sweep(h, a, b):
    cross = (a[0] - h[0]) * (b[1] - h[1]) - (a[1] - h[1]) * (b[0] - h[0])
    # SVG y axis is flipped, so a positive cross in plan coords is clockwise on screen
    return 1 if cross < 0 else 0


def _dim(cv: _Canvas, p, q, label, font, vertical=False):
    col = "#7a6f63"
    cv.line(p, q, stroke=col, stroke_width=0.8)
    tick = 0.8
    for pt in (p, q):
        if vertical:
            cv.line((pt[0] - tick, pt[1] - tick), (pt[0] + tick, pt[1] + tick), stroke=col, stroke_width=1)
        else:
            cv.line((pt[0] - tick, pt[1] - tick), (pt[0] + tick, pt[1] + tick), stroke=col, stroke_width=1)
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    if vertical:
        cv.text(mx - 1.3, my, label, size=font * 0.9, fill=col, rotate=-90)
    else:
        cv.text(mx, my + 1.3, label, size=font * 0.9, fill=col)
