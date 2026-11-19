"""Door swing clearance: a door must be able to open without hitting fixtures,
furniture or another door's swing (company rule 13)."""
from __future__ import annotations

import math
from functools import lru_cache

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from .layout import Door, Layout
from .module_library import transform_point
from .rules import Rulebook


@lru_cache(maxsize=50000)
def _space_fixtures(prims: tuple, ins: tuple, theta: float):
    parts = []
    for kind, _layer, data in prims:
        if kind == "poly":
            pts, closed = data
            tp = [transform_point(p, ins, theta) for p in pts]
            if closed and len(tp) >= 3:
                poly = Polygon(tp)
                parts.append(poly if poly.is_valid else poly.buffer(0))
            elif len(tp) >= 2:
                parts.append(LineString(tp))
        elif kind == "line":
            parts.append(LineString([transform_point(p, ins, theta) for p in data]))
        elif kind == "circle":
            c, r = data
            parts.append(Point(transform_point(c, ins, theta)).buffer(r, 8))
    return unary_union(parts) if parts else None


def fixture_geometry(lay: Layout, rb: Rulebook) -> list:
    """Fixture / furniture footprint of every room (world feet), one geometry per room."""
    from .render_svg import fixture_placements  # local import to avoid a cycle

    out = []
    for _s, _m, ins, theta, prims in fixture_placements(lay, rb):
        g = _space_fixtures(prims, (round(ins[0], 4), round(ins[1], 4)), round(theta, 3))
        if g is not None:
            out.append(g)
    return out


@lru_cache(maxsize=200000)
def _swing(key: tuple):
    from .render_svg import door_leaves

    x, y, axis, width, kind, into, hinge, leaves, wall, ext, L, D = key
    d = Door(x, y, axis, width, kind, into=into, hinge=hinge, wall=wall, leaves=leaves)
    polys = []
    for hinge_pt, leaf, closed in door_leaves(d, ext, L, D):
        r = math.hypot(leaf[0] - hinge_pt[0], leaf[1] - hinge_pt[1])
        a0 = math.atan2(closed[1] - hinge_pt[1], closed[0] - hinge_pt[0])
        a1 = math.atan2(leaf[1] - hinge_pt[1], leaf[0] - hinge_pt[0])
        diff = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # signed short way, +-90 deg
        pts = [hinge_pt] + [(hinge_pt[0] + r * math.cos(a0 + diff * k / 10),
                             hinge_pt[1] + r * math.sin(a0 + diff * k / 10)) for k in range(11)]
        polys.append(Polygon(pts))
    return unary_union(polys).buffer(-0.04) if polys else None


def swing_area(d: Door, ext: float, L: float, D: float):
    """Area a swinging door sweeps (one quarter circle per leaf)."""
    if d.kind not in ("interior", "exterior"):
        return None
    return _swing((round(d.x, 4), round(d.y, 4), d.axis, d.width, d.kind, d.into, d.hinge, d.leaves, d.wall,
                   ext, L, D))


def door_conflict(d: Door, lay: Layout, rb: Rulebook, fixtures, others: list[Door]) -> str:
    """'' if the door swings clear, else a short reason."""
    ext = rb.b("ext_wall")
    area = swing_area(d, ext, lay.length, lay.width)
    if area is None or area.is_empty:
        return ""
    for g in fixtures or []:
        if area.intersects(g):
            return "swings into a fixture"
    for o in others:
        if o is d or o.kind not in ("interior", "exterior"):
            continue
        if abs(o.x - d.x) > (o.width + d.width) or abs(o.y - d.y) > (o.width + d.width):
            continue
        oa = swing_area(o, ext, lay.length, lay.width)
        if oa is not None and area.intersection(oa).area > 0.05:
            return "swings into another door"
    return ""
