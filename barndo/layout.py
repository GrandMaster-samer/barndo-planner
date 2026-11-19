"""Layout data model and small geometry helpers (all units feet).

Coordinate system: x runs along the building length (0 .. L), y across the
width (0 = FRONT wall, D = BACK wall). Front porch sits at y < 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

EPS = 1e-6
SIDES = ("S", "N", "W", "E")  # S = front/bottom edge (y0), N = back/top edge (y1), W = left (x0), E = right (x1)
OPPOSITE = {"S": "N", "N": "S", "W": "E", "E": "W"}
MIRROR_X = {"S": "S", "N": "N", "W": "E", "E": "W"}

CIRCULATION = {"hall", "link", "shop_link"}
OPEN_TO_EACH_OTHER = {"great_room", "hall", "link", "shop_link"}


@dataclass
class Space:
    id: str
    kind: str          # module id, or hall / link / shop_link / shop
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    door_side: Optional[str] = None   # side of the room's main entry (defines module orientation)
    anchor: str = ""                  # override of the module's fixture anchor (layout variants)
    column: str = ""                  # A / B / H / G / S - for debugging & tests
    wing: str = ""                    # L / R

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def local_wd(self) -> tuple[float, float]:
        """(width along door wall, depth into room)."""
        if self.door_side in ("W", "E"):
            return self.h, self.w
        return self.w, self.h


@dataclass
class Door:
    x: float                 # center
    y: float
    axis: str                # 'x' = door lies in a horizontal wall, 'y' = vertical wall
    width: float
    kind: str                # interior | exterior | overhead | opening
    into: int = 1            # +1 = swings toward +y (axis x) or +x (axis y); -1 opposite
    hinge: int = -1          # -1 hinge at the low end, +1 at the high end
    serves: str = ""         # space id
    wall: str = "int"        # int | ext | shop
    height: float = 6.667
    leaves: int = 1          # 2 = double door


@dataclass
class Window:
    x: float
    y: float
    axis: str
    width: float
    serves: str = ""
    height: float = 4.0
    units: int = 1           # 2 = double (pair of standard windows)


@dataclass
class Layout:
    id: str
    length: float
    width: float
    living_length: float
    shop_length: float
    shop_side: str
    spaces: list[Space] = field(default_factory=list)
    doors: list[Door] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    posts: list[tuple[float, float]] = field(default_factory=list)
    porches: list[tuple[float, float, float, float]] = field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    estimate: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    signature: str = ""
    requirements: dict[str, Any] = field(default_factory=dict)
    concept: str = ""
    rule_checks: list[dict[str, Any]] = field(default_factory=list)

    # -- helpers ----------------------------------------------------------
    def space(self, sid: str) -> Space:
        for s in self.spaces:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def rooms(self) -> list[Space]:
        return [s for s in self.spaces if s.kind not in CIRCULATION and s.kind != "shop"]

    def is_exterior_edge(self, side: str, s: Space) -> bool:
        if side == "S":
            return abs(s.y0) < EPS
        if side == "N":
            return abs(s.y1 - self.width) < EPS
        if side == "W":
            return abs(s.x0) < EPS and not (self.shop_side == "left" and self.shop_length > 0 and s.kind != "shop")
        if side == "E":
            return abs(s.x1 - self.length) < EPS and not (self.shop_side == "right" and self.shop_length > 0 and s.kind != "shop")
        return False

    def exterior_sides(self, s: Space) -> list[str]:
        return [side for side in SIDES if self.is_exterior_edge(side, s)]

    def mirror(self) -> None:
        """Mirror left/right in place (used to put the shop on the left)."""
        L = self.length
        for s in self.spaces:
            s.x0, s.x1 = L - s.x1, L - s.x0
            if s.door_side:
                s.door_side = MIRROR_X[s.door_side]
            s.wing = {"L": "R", "R": "L"}.get(s.wing, s.wing)
        for d in self.doors:
            d.x = L - d.x
            if d.axis == "y":
                d.into = -d.into
            else:
                d.hinge = -d.hinge
        for w in self.windows:
            w.x = L - w.x
        self.posts = [(L - x, y) for x, y in self.posts]
        self.porches = [(L - x1, y0, L - x0, y1) for x0, y0, x1, y1 in self.porches]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for s, sd in zip(self.spaces, d["spaces"]):
            sd["area"] = round(s.area, 1)
            sd["clear"] = clear_dims(self, s)
        return d


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def shared_edge(a: Space, b: Space) -> Optional[tuple[str, float, float, float]]:
    """Return (axis, fixed, lo, hi) of the boundary a and b share, or None.

    axis 'x' = horizontal segment at y=fixed from x=lo..hi
    axis 'y' = vertical segment at x=fixed from y=lo..hi
    """
    # vertical contact
    for xa, xb in ((a.x1, b.x0), (a.x0, b.x1)):
        if abs(xa - xb) < EPS:
            lo, hi = max(a.y0, b.y0), min(a.y1, b.y1)
            if hi - lo > EPS:
                return ("y", xa, lo, hi)
    for ya, yb in ((a.y1, b.y0), (a.y0, b.y1)):
        if abs(ya - yb) < EPS:
            lo, hi = max(a.x0, b.x0), min(a.x1, b.x1)
            if hi - lo > EPS:
                return ("x", ya, lo, hi)
    return None


def side_of(a: Space, edge: tuple[str, float, float, float]) -> str:
    axis, fixed, _, _ = edge
    if axis == "y":
        return "W" if abs(fixed - a.x0) < EPS else "E"
    return "S" if abs(fixed - a.y0) < EPS else "N"


def fmt_ft(v: float) -> str:
    """12.5 -> 12'-6\" """
    total_in = int(round(v * 12))
    ft, inch = divmod(total_in, 12)
    return f"{ft}'-{inch}\""


def clear_dims(layout: Layout, s: Space, ext: float = 0.5, intw: float = 0.333) -> tuple[float, float]:
    """Approximate clear (finished) room dimensions after wall thickness."""
    ext_sides = set(layout.exterior_sides(s))
    w, h = s.w, s.h
    for side in ("W", "E"):
        w -= ext if side in ext_sides else intw / 2
    for side in ("S", "N"):
        h -= ext if side in ext_sides else intw / 2
    return (round(w, 2), round(h, 2))


def layout_from_dict(d: dict[str, Any]) -> Layout:
    """Rebuild a Layout saved with Layout.to_dict()."""
    d = dict(d)
    spaces = []
    for s in d.pop("spaces", []):
        s = {k: v for k, v in s.items() if k in Space.__dataclass_fields__}
        spaces.append(Space(**s))
    doors = [Door(**x) for x in d.pop("doors", [])]
    windows = [Window(**x) for x in d.pop("windows", [])]
    posts = [tuple(p) for p in d.pop("posts", [])]
    porches = [tuple(p) for p in d.pop("porches", [])]
    d = {k: v for k, v in d.items() if k in Layout.__dataclass_fields__}
    return Layout(spaces=spaces, doors=doors, windows=windows, posts=posts, porches=porches, **d)
