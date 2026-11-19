"""The layout engine.

How a barndo plan is assembled
------------------------------
The living area is a rectangle (building width D x living length). It is
filled left-to-right with "blocks":

    [ WING ][ GREAT ROOM ][ WING ][ SHOP ]

* GREAT ROOM - open kitchen / dining / living, full building depth.
* WING      - a bedroom wing made of two columns of room modules stacked
              front-to-back with a hallway between them:

                 outer column A | hall | inner column B | great room

              Column A sits on the outside (end wall or shop wall), so it
              holds bedrooms, the primary suite and the office. Column B
              sits against the great room and holds baths, laundry, pantry,
              closets. A short "link" in column B connects the hall to the
              great room. On the shop side a link (or the mudroom/laundry)
              connects the hall to the shop.

Rooms are the modules from the rulebook. Every room is sized inside its
min/max limits, so the engine never produces a room that breaks the rules.
The engine tries many arrangements (which wing gets the primary suite, room
order, column depths...), throws away anything invalid (no egress window,
door doesn't fit, great room too narrow...), scores the rest and returns the
best distinct options.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .design_rules import check_layout, hard_failures
from .layout import EPS, OPPOSITE, Door, Layout, Space, Window, shared_edge, side_of
from .clearance import door_conflict, fixture_geometry
from .module_library import placement
from .requirements import Requirements
from .rules import Rulebook, load_rulebook
from .walls import interior_wall_length


class LayoutError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Plan representation
# ---------------------------------------------------------------------------
@dataclass
class Item:
    kind: str
    door: str = "hall"   # hall | ensuite | great | none


@dataclass
class WingPlan:
    side: str                       # L | R | B (back)
    col_a: list[Item] = field(default_factory=list)
    col_b: list[Item] = field(default_factory=list)
    hall: bool = True               # False = rooms open straight onto the great room


@dataclass
class ColumnFit:
    depth: float
    items: list[Item]
    sizes: list[float]
    score: float


@dataclass
class WingFit:
    side: str
    a: ColumnFit
    b: Optional[ColumnFit]
    hall: float

    @property
    def width(self) -> float:
        return self.a.depth + self.hall + (self.b.depth if self.b else 0.0)

    @property
    def score(self) -> float:
        return self.a.score + (self.b.score if self.b else 0.0)


EXTERIOR_KINDS = None  # resolved from rulebook (needs_exterior)


# ---------------------------------------------------------------------------
# Random plan generation
# ---------------------------------------------------------------------------
def _available(rb: Rulebook, kind: str) -> bool:
    return kind in rb.modules


def room_program(req: Requirements, rb: Rulebook) -> dict[str, int]:
    prog = Counter()
    prog["master_bedroom"] = 1
    prog["master_bath"] = 1
    if req.walk_in_closet and _available(rb, "master_wic"):
        prog["master_wic"] = 1
    prog["bedroom"] = req.bedrooms - 1
    prog["full_bath"] = req.full_baths - 1
    # company rule 6: laundry and mudroom are always one room
    laundry_mud = int(req.laundry or req.mudroom)
    for kind, n in (("half_bath", req.half_baths), ("laundry_mud", laundry_mud), ("pantry", int(req.pantry)),
                    ("office", int(req.office))):
        if n and _available(rb, kind):
            prog[kind] += n
    return {k: v for k, v in prog.items() if v > 0}


def _arrange(rng: random.Random, groups: list[list[Item]], rb: Rulebook, ends_only_exterior: bool) -> list[Item]:
    """Order groups in a column. If only the ends of the column touch an
    exterior wall, rooms that need a window go to the ends."""
    rng.shuffle(groups)
    if ends_only_exterior:
        def needs_ext(g):
            return any(i.kind in rb.modules and rb.m(i.kind).needs_exterior for i in g)
        ext = [g for g in groups if needs_ext(g)]
        other = [g for g in groups if not needs_ext(g)]
        first = ext[0:1]
        last = ext[1:2]
        middle = ext[2:] + other
        rng.shuffle(middle)
        groups = first + middle + last
        # make the exterior room of an end group sit at the very end
        if first and len(first[0]) > 1:
            g = first[0]
            idx = next(k for k, i in enumerate(g) if rb.m(i.kind).needs_exterior)
            if idx != 0:
                first[0] = list(reversed(g)) if idx == len(g) - 1 else g
        if last and len(last[0]) > 1:
            g = last[0]
            idx = next(k for k, i in enumerate(g) if rb.m(i.kind).needs_exterior)
            if idx != len(g) - 1:
                last[0] = list(reversed(g)) if idx == 0 else g
        groups = first + middle + last
    return [i for g in groups for i in g]


def random_plan(rng: random.Random, req: Requirements, rb: Rulebook, extra_flex: int = 0) -> tuple[list[WingPlan], dict]:
    prog = room_program(req, rb)
    if extra_flex and _available(rb, "flex"):
        prog["flex"] = prog.get("flex", 0) + extra_flex
    has_shop = req.shop_length > 0
    n_rooms = sum(prog.values())

    rear_p = 0.5 if req.living_length <= 50 else 0.15
    if rng.random() < rear_p:
        sides = ("B",)   # one wing along the back wall, great room across the front
    elif n_rooms <= 4:
        sides = rng.choices([("L",), ("R",), ("L", "R")], weights=[0.55, 0.2, 0.25])[0]
    else:
        sides = rng.choices([("L",), ("R",), ("L", "R")], weights=[0.25, 0.1, 0.65])[0]
    wings = {s: {"A": [], "B": []} for s in sides}

    # primary suite
    if len(sides) == 2:
        master_side = "L" if (has_shop and rng.random() < 0.7) else rng.choice(sides)
    else:
        master_side = sides[0]
    bed, bath = Item("master_bedroom", "hall"), Item("master_bath", "ensuite")
    suite = [bed, bath]
    if prog.get("master_wic"):
        wic = Item("master_wic", "ensuite")
        suite = rng.choice([[bed, bath, wic], [wic, bath, bed], [bath, bed, wic], [wic, bed, bath]])
    elif rng.random() < 0.5:
        suite = [bath, bed]
    wings[master_side]["A"].append(suite)

    other_side = [s for s in sides if s != master_side]

    def pick_wing(prefer_other: float = 0.75) -> str:
        if other_side and rng.random() < prefer_other:
            return other_side[0]
        return rng.choice(sides)

    for _ in range(prog.get("bedroom", 0)):
        w = pick_wing(0.8)
        col = "B" if rng.random() < 0.12 else "A"
        wings[w][col].append([Item("bedroom")])
    for _ in range(prog.get("flex", 0)):
        w = pick_wing(0.5)
        wings[w]["A"].append([Item("flex")])
    if prog.get("office"):
        w = pick_wing(0.5)
        wings[w]["B" if rng.random() < 0.15 else "A"].append([Item("office")])
    for _ in range(prog.get("full_bath", 0)):
        w = pick_wing(0.75)
        wings[w]["B" if rng.random() < 0.85 else "A"].append([Item("full_bath")])
    for _ in range(prog.get("half_bath", 0)):
        w = rng.choice(sides)
        wings[w]["B"].append([Item("half_bath")])
    shop_wing = "R" if (has_shop and "R" in sides) else ("B" if has_shop and "B" in sides else None)
    if prog.get("laundry_mud"):
        w = shop_wing if (shop_wing and rng.random() < 0.75) else rng.choice(sides)
        wings[w]["A" if (w == shop_wing and rng.random() < 0.7) else "B"].append([Item("laundry_mud")])
    if prog.get("pantry"):
        w = rng.choice(sides)
        wings[w]["B" if rng.random() < 0.85 else "A"].append([Item("pantry")])

    # company rules 2 + 9: avoid hallways whenever rooms can open straight into the open space
    no_hall_p = 0.6 if req.living_length <= 50 else 0.4
    halls = {}
    for s in sides:
        halls[s] = bool(wings[s]["B"]) and rng.random() >= no_hall_p
        if not halls[s]:
            wings[s]["A"] += wings[s]["B"]
            wings[s]["B"] = []
    _rebalance(rng, wings, halls, req, rb)

    plans = []
    for s in sides:
        a_groups, b_groups = wings[s]["A"], wings[s]["B"]
        hall = halls[s] and bool(b_groups)
        a_ends_only = (s == "R" and has_shop)
        if s == "B":
            a_ends_only = False
        col_a = _arrange(rng, a_groups, rb, a_ends_only)
        col_b = _arrange(rng, b_groups, rb, True)
        if not hall:
            for it in col_a:
                if it.kind == "pantry":
                    it.door = "hall"  # 'hall' resolves to the great room when there is no hall
        for it in col_b:
            if it.kind == "pantry":
                it.door = "great" if rng.random() < 0.8 else "hall"
        if col_b:
            col_b.insert(rng.randint(0, len(col_b)), Item("link", "none"))
        if s == "R" and has_shop and not any(i.kind == "laundry_mud" for i in col_a):
            col_a.insert(rng.randint(0, len(col_a)), Item("shop_link", "none"))
        if not col_a:
            # a wing always needs an outer column; give it a storage room
            col_a = [Item("storage")]
        plans.append(WingPlan(s, col_a, col_b, hall))
    style = {
        "kitchen": rng.choice(["back-left", "back-center", "back-center", "back-right"]),
        "entry_end": rng.choice(["low", "high", "center"]),
    }
    return plans, style


def _min_len(it: Item, rb: Rulebook) -> float:
    m = rb.m(it.kind)
    return m.min_d if it.door == "ensuite" else m.min_w


def _rebalance(rng: random.Random, wings: dict, halls: dict, req: Requirements, rb: Rulebook) -> None:
    """Move rooms out of columns that can't physically hold them (sum of minimum sizes
    longer than the column) into columns that can."""
    link = rb.b("link_width")

    def total(w):
        return req.living_length if w == "B" else req.building_width

    def load(w, c):
        groups = wings[w][c]
        n = sum(_min_len(it, rb) for g in groups for it in g)
        return n + (link if c == "B" and groups else 0)

    def needs_ext(g):
        return any(rb.m(i.kind).needs_exterior for i in g)

    cols = [(w, c) for w in wings for c in ("A", "B") if c == "A" or halls[w]]
    for _ in range(30):
        over = [(w, c) for w, c in cols if load(w, c) > total(w) + EPS]
        if not over:
            return
        w, c = over[0]
        movable = [g for g in wings[w][c] if not any(i.kind.startswith("master_") for i in g)]
        if not movable:
            return
        g = rng.choice(movable)
        size = sum(_min_len(i, rb) for i in g)
        targets = []
        for w2, c2 in cols:
            if (w2, c2) == (w, c):
                continue
            extra = link if (c2 == "B" and not wings[w2][c2]) else 0
            if load(w2, c2) + size + extra > total(w2) + EPS:
                continue
            if c2 == "B" and needs_ext(g) and sum(needs_ext(x) for x in wings[w2]["B"]) >= 2:
                continue  # only the two ends of an inner column reach an outside wall
            targets.append((w2, c2))
        if not targets:
            return
        w2, c2 = rng.choice(targets)
        wings[w][c].remove(g)
        wings[w2][c2].append(g)


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
def _y_range(item: Item, depth: float, rb: Rulebook) -> Optional[tuple[float, float, float]]:
    if item.kind in ("link", "shop_link"):
        lw = rb.b("link_width")
        return (lw, lw, lw)
    m = rb.m(item.kind)
    if item.door == "ensuite":
        if not (m.min_w - EPS <= depth <= m.max_w + EPS):
            return None
        return (m.min_d, m.max_d, m.pref_d)
    if not (m.min_d - EPS <= depth <= m.max_d + EPS):
        return None
    return (m.min_w, m.max_w, m.pref_w)


def _fill(ranges: list[tuple[float, float, float]], total: float) -> Optional[list[float]]:
    lo = sum(r[0] for r in ranges)
    hi = sum(r[1] for r in ranges)
    if lo > total + EPS or hi < total - EPS:
        return None
    cur = [min(max(r[2], r[0]), r[1]) for r in ranges]
    diff = total - sum(cur)
    if abs(diff) > EPS:
        room = [(r[1] - c) if diff > 0 else (c - r[0]) for r, c in zip(ranges, cur)]
        tot = sum(room)
        if tot < abs(diff) - EPS:
            return None
        cur = [c + diff * rm / tot for c, rm in zip(cur, room)]
    # snap boundaries to 6"
    out, acc, prev = [], 0.0, 0.0
    for k, c in enumerate(cur):
        acc += c
        b = total if k == len(cur) - 1 else round(acc * 2) / 2
        out.append(b - prev)
        prev = b
    for (lo_, hi_, _), s in zip(ranges, out):
        if s < lo_ - 0.26 or s > hi_ + 0.26 or s <= 0:
            return None
    return out


def fit_column(items: list[Item], depth: float, total: float, rb: Rulebook) -> Optional[ColumnFit]:
    items = list(items)
    ranges = [_y_range(i, depth, rb) for i in items]
    if any(r is None for r in ranges):
        return None
    hi = sum(r[1] for r in ranges)
    fillers = 0
    while hi < total - EPS and fillers < 2:
        st = Item("storage")
        r = _y_range(st, depth, rb)
        if r is None:
            return None
        if fillers == 0:
            items.append(st)
            ranges.append(r)
        else:
            items.insert(0, st)
            ranges.insert(0, r)
        hi += r[1]
        fillers += 1
    sizes = _fill(ranges, total)
    if sizes is None:
        return None
    score = 0.0
    for it, s in zip(items, sizes):
        if it.kind in ("link", "shop_link"):
            continue
        m = rb.m(it.kind)
        if it.door == "ensuite":
            lw, ld = depth, s
        else:
            lw, ld = s, depth
        if it.kind == "storage":
            score -= 0.08 * s * depth / 10
            continue
        score -= abs(lw - m.pref_w) / m.pref_w + abs(ld - m.pref_d) / m.pref_d
    return ColumnFit(depth, items, sizes, score)


def fit_wing(plan: WingPlan, total: float, rb: Rulebook, keep: int = 10) -> list[WingFit]:
    hall = rb.b("hall_width") if plan.hall else 0.0
    a_opts = [f for d in rb.float_list("col_a_depths") if (f := fit_column(plan.col_a, d, total, rb))]
    if plan.col_b:
        b_opts = [f for d in rb.float_list("col_b_depths") if d > 0 and (f := fit_column(plan.col_b, d, total, rb))]
    else:
        b_opts = [None]
    fits = [WingFit(plan.side, a, b, hall) for a in a_opts for b in b_opts]
    fits.sort(key=lambda f: f.score, reverse=True)
    return fits[:keep]


# ---------------------------------------------------------------------------
# Building the geometry
# ---------------------------------------------------------------------------
class Invalid(Exception):
    pass


_NAMES_COUNTER_KINDS = {"bedroom": "Bedroom", "full_bath": "Bath", "half_bath": "Half Bath"}


def _place_on_wall(lo: float, hi: float, width: float, preferred: float, obstacles: list[tuple[float, float]],
                   margin: float = 0.5) -> Optional[float]:
    """Find a center for an opening of `width` on a wall segment [lo, hi]
    nearest to `preferred`, not overlapping any obstacle interval."""
    a, b = lo + width / 2 + margin, hi - width / 2 - margin
    if a > b + EPS:
        return None
    preferred = min(max(preferred, a), b)
    steps = int((b - a) / 0.25) + 2
    cands = sorted({round(min(max(preferred + k * 0.25 * sgn, a), b), 3) for k in range(steps) for sgn in (1, -1)},
                   key=lambda c: abs(c - preferred))
    for c in cands:
        o_lo, o_hi = c - width / 2, c + width / 2
        if all(o_hi <= ob_lo + EPS or o_lo >= ob_hi - EPS for ob_lo, ob_hi in obstacles):
            return c
    return None


class Builder:
    def __init__(self, req: Requirements, rb: Rulebook):
        self.req, self.rb = req, rb
        self.D = req.building_width
        self.L = req.building_length
        self.shop = req.shop_length
        self.living = self.L - self.shop
        self.bay = rb.b("bay_spacing")
        self.post = rb.b("post_size")
        self.clear = rb.b("opening_clearance")

    # -- posts ---------------------------------------------------------------
    def posts(self) -> list[tuple[float, float]]:
        pts = set()
        n = max(1, round(self.L / self.bay))
        step_x = self.L / n
        for i in range(n + 1):
            x = round(i * step_x, 3)
            pts.add((x, 0.0))
            pts.add((x, self.D))
        m = max(1, round(self.D / self.bay))
        step_y = self.D / m
        for j in range(m + 1):
            y = round(j * step_y, 3)
            pts.add((0.0, y))
            pts.add((self.L, y))
        return sorted(pts)

    def wall_obstacles(self, lay: Layout, axis: str, fixed: float) -> list[tuple[float, float]]:
        obs = []
        half = self.post / 2 + self.clear
        for x, y in lay.posts:
            if axis == "x" and abs(y - fixed) < EPS:
                obs.append((x - half, x + half))
            elif axis == "y" and abs(x - fixed) < EPS:
                obs.append((y - half, y + half))
        for d in lay.doors:
            if d.axis == axis and abs((d.y if axis == "x" else d.x) - fixed) < EPS:
                c = d.x if axis == "x" else d.y
                obs.append((c - d.width / 2 - 0.5, c + d.width / 2 + 0.5))
        for w in lay.windows:
            if w.axis == axis and abs((w.y if axis == "x" else w.x) - fixed) < EPS:
                c = w.x if axis == "x" else w.y
                obs.append((c - w.width / 2 - 0.75, c + w.width / 2 + 0.75))
        return obs

    # -- main ------------------------------------------------------------------
    def build(self, wings: dict[str, WingFit], style: Optional[dict] = None) -> Layout:
        req, rb, D = self.req, self.rb, self.D
        self.style = style or {"kitchen": "back-center", "entry_end": "center"}
        lay = Layout(id="", length=self.L, width=D, living_length=self.living, shop_length=self.shop,
                     shop_side="right", requirements=req.model_dump())
        counters = Counter()
        gm = rb.m("great_room")
        if "B" in wings:
            wf = wings["B"]
            gd = D - wf.width
            if not gm.fits(self.living, gd):
                raise Invalid("great_room_width")
            # kitchen goes on the end wall so it keeps a window (company rule 6)
            lay.spaces.append(Space("great_room", "great_room", gm.name, 0.0, 0.0, self.living, gd, door_side="E",
                                    column="G", anchor=self.style["kitchen"]))
            self._add_rear_wing(lay, wf, gd, counters)
            return self._finish(lay)
        x = 0.0
        if "L" in wings:
            x = self._add_wing(lay, wings["L"], 0.0, counters)
        gx0 = x
        gx1 = self.living - (wings["R"].width if "R" in wings else 0.0)
        gw = gx1 - gx0
        if gw < gm.min_w - EPS or gw > gm.max_w + EPS:
            raise Invalid("great_room_width")
        if not gm.min_d - EPS <= D <= gm.max_d + EPS:
            raise Invalid("great_room_depth")
        lay.spaces.append(Space("great_room", "great_room", gm.name, gx0, 0.0, gx1, D, door_side="S", column="G",
                                anchor=self.style["kitchen"]))
        if "R" in wings:
            self._add_wing(lay, wings["R"], gx1, counters)
        return self._finish(lay)

    def _finish(self, lay: Layout) -> Layout:
        req, D = self.req, self.D
        if self.shop > 0:
            lay.spaces.append(Space("shop", "shop", "Shop", self.living, 0.0, self.L, D, column="S"))
        if req.front_porch_depth > 0:
            lay.porches.append((0.0, -req.front_porch_depth, self.living, 0.0))
        if req.back_porch_depth > 0:
            lay.porches.append((0.0, D, self.living, D + req.back_porch_depth))
        lay.posts = self.posts()
        self._interior_doors(lay)
        self._trim_halls(lay)
        self._exterior_doors(lay)
        self._windows(lay)
        return lay

    def _add_wing(self, lay: Layout, wf: WingFit, x0: float, counters: Counter) -> float:
        hall = wf.hall
        a, b = wf.a, wf.b
        bd = b.depth if b else 0.0
        if wf.side == "L":
            xa, xh, xb = x0, x0 + a.depth, x0 + a.depth + hall
            a_door, b_door, b_great = "E", "W", "E"
        else:
            xb, xh, xa = x0, x0 + bd, x0 + bd + hall
            a_door, b_door, b_great = "W", "E", "W"
        if hall > 0:
            lay.spaces.append(Space(f"{wf.side}_hall", "hall", "Hall", xh, 0.0, xh + hall, self.D, column="H", wing=wf.side))
        self._stack(lay, wf.side, "A", a, xa, a_door, None, counters)
        if b:
            self._stack(lay, wf.side, "B", b, xb, b_door, b_great, counters)
        return x0 + wf.width

    def _add_rear_wing(self, lay: Layout, wf: WingFit, y0: float, counters: Counter) -> None:
        """Wing along the back wall: inner column B (front), hall, outer column A (back wall)."""
        bd = wf.b.depth if wf.b else 0.0
        yb, yh, ya = y0, y0 + bd, y0 + bd + wf.hall
        if wf.hall > 0:
            lay.spaces.append(Space("B_hall", "hall", "Hall", 0.0, yh, self.living, yh + wf.hall, column="H", wing="B"))
        self._stack(lay, "B", "A", wf.a, ya, "S", None, counters, along="x")
        if wf.b:
            self._stack(lay, "B", "B", wf.b, yb, "N", "S", counters, along="x")

    def _stack(self, lay, side, col, cf: ColumnFit, x0, hall_door, great_door, counters, along: str = "y"):
        y = 0.0
        made = []
        for k, (it, s) in enumerate(zip(cf.items, cf.sizes)):
            sid = f"{side}{col}{k}_{it.kind}"
            if it.kind in ("link", "shop_link"):
                name = ""
            else:
                m = self.rb.m(it.kind)
                if it.kind in _NAMES_COUNTER_KINDS:
                    counters[it.kind] += 1
                    n = counters[it.kind] + (1 if it.kind in ("bedroom", "full_bath") else 0)
                    name = f"{_NAMES_COUNTER_KINDS[it.kind]} {n}" if (it.kind != "half_bath" or self.req.half_baths > 1) else m.name
                else:
                    name = m.name
            if it.door == "hall" or it.kind == "storage":
                ds = hall_door
            elif it.door == "great":
                ds = great_door
            else:
                ds = None
            if along == "y":
                sp = Space(sid, it.kind, name, x0, y, x0 + cf.depth, y + s, door_side=ds, column=col, wing=side)
            else:
                sp = Space(sid, it.kind, name, y, x0, y + s, x0 + cf.depth, door_side=ds, column=col, wing=side)
            if it.kind in self.rb.modules:
                sp.anchor = self.rb.m(it.kind).fixture_anchor
            sp._item = it  # type: ignore[attr-defined]
            lay.spaces.append(sp)
            made.append(sp)
            y += s
        # ensuite orientation: door faces the partner room
        for k, sp in enumerate(made):
            it = sp._item  # type: ignore[attr-defined]
            if it.door != "ensuite":
                continue
            partner = self._ensuite_partner(made, k)
            if partner is None:
                raise Invalid("ensuite_access")
            if along == "y":
                sp.door_side = "S" if partner.y1 <= sp.y0 + EPS else "N"
            else:
                sp.door_side = "W" if partner.x1 <= sp.x0 + EPS else "E"
            sp._partner = partner.id  # type: ignore[attr-defined]

    @staticmethod
    def _ensuite_partner(col: list[Space], k: int) -> Optional[Space]:
        me = col[k]
        nbrs = [col[i] for i in (k - 1, k + 1) if 0 <= i < len(col)]
        if me.kind == "master_bath":
            for n in nbrs:
                if n.kind == "master_bedroom":
                    return n
            return None
        for want in ("master_bedroom", "master_bath"):
            for n in nbrs:
                if n.kind == want:
                    return n
        return None

    # -- doors ---------------------------------------------------------------
    def _posts_to_jambs(self, lay: Layout, axis: str, fixed: float, c: float, width: float) -> None:
        keep = []
        for px, py in lay.posts:
            along, at = (px, py) if axis == "x" else (py, px)
            if abs(at - fixed) < EPS and c - width / 2 - self.post / 2 - EPS < along < c + width / 2 + self.post / 2 + EPS:
                continue
            keep.append((px, py))
        for jamb in (c - width / 2 - self.post / 2, c + width / 2 + self.post / 2):
            keep.append((jamb, fixed) if axis == "x" else (fixed, jamb))
        lay.posts = sorted(set(keep))

    def _is_post_obstacle(self, lay: Layout, ob: tuple[float, float], axis: str, fixed: float) -> bool:
        mid = (ob[0] + ob[1]) / 2
        return any(abs((px if axis == "x" else py) - mid) < EPS and abs((py if axis == "x" else px) - fixed) < EPS
                   for px, py in lay.posts)

    def _ref_point(self, lay: Layout, room: Space) -> tuple[float, float]:
        """Where people arrive from: the wing's link to the great room, else the hall, else the great room."""
        for kind in ("link", "hall"):
            for sp in lay.spaces:
                if sp.kind == kind and sp.wing == room.wing:
                    return (sp.cx, sp.cy)
        g = next(sp for sp in lay.spaces if sp.kind == "great_room")
        return (g.cx, g.cy)

    def _door_on(self, lay: Layout, room: Space, other: Space, width: float, kind="interior", wall="int",
                 prefer: Optional[float] = None, ref: Optional[tuple[float, float]] = None, leaves: int = 1) -> Door:
        """Put a door on the wall between `room` and `other`.

        Company rule 3: doors sit at the side of the wall (next to a corner), not in the middle.
        The corner nearest to where people arrive from is used, unless another door already
        sits there.
        """
        e = shared_edge(room, other)
        if not e:
            raise Invalid("door_no_edge")
        axis, fixed, lo, hi = e
        if hi - lo < width + 0.5 - EPS:
            raise Invalid("door_too_tight")
        off = self.rb.b("door_corner_offset") + self.rb.b("int_wall") / 2
        obstacles = self.wall_obstacles(lay, axis, fixed) if wall == "ext" else []
        if prefer is not None:
            prefs = [prefer]
        else:
            rlo, rhi = (room.y0, room.y1) if axis == "y" else (room.x0, room.x1)
            end_lo = max(lo, rlo) + off + width / 2
            end_hi = min(hi, rhi) - off - width / 2
            r = ref or self._ref_point(lay, room)
            target = r[1] if axis == "y" else r[0]
            prefs = sorted([end_lo, end_hi], key=lambda c: abs(c - target)) + [(lo + hi) / 2]
        existing = [d for d in lay.doors if d.serves == room.id or self._door_on_space(d, room)]
        height = self.rb.b("door_height")
        into_room = (1 if abs(room.x0 - fixed) < EPS else -1) if axis == "y" else (1 if abs(room.y0 - fixed) < EPS else -1)
        # swinging out of the room is fine into a bedroom (en-suite bath / closet) or the shop,
        # never into a hallway or the great room
        can_swing_out = other.kind in ("master_bedroom", "master_bath", "shop")
        fixtures = getattr(self, "_fixtures", None)
        d = None
        for pref in prefs:
            cand = _place_on_wall(lo, hi, width, pref, obstacles, margin=min(off, (hi - lo - width) / 2))
            if cand is None:
                continue
            pt = (fixed, cand) if axis == "y" else (cand, fixed)
            if any(((x.x - pt[0]) ** 2 + (x.y - pt[1]) ** 2) ** 0.5 < (x.width + width) / 2 + 0.4 for x in existing):
                continue
            corner_hinge = -1 if (cand - lo) <= (hi - cand) else 1
            # company rule 13: try hinge / swing combinations until the door swings clear
            options = [(into_room, corner_hinge), (into_room, -corner_hinge)]
            if can_swing_out:
                options += [(-into_room, corner_hinge), (-into_room, -corner_hinge)]
            for into, hinge in options:
                if axis == "y":
                    trial = Door(fixed, cand, "y", width, kind, into=into, hinge=hinge, serves=room.id, wall=wall,
                                 height=height, leaves=leaves)
                else:
                    trial = Door(cand, fixed, "x", width, kind, into=into, hinge=hinge, serves=room.id, wall=wall,
                                 height=height, leaves=leaves)
                if not door_conflict(trial, lay, self.rb, fixtures, lay.doors):
                    d = trial
                    break
            if d is not None:
                break
        if d is None:
            raise Invalid("door_swing_blocked")
        lay.doors.append(d)
        return d

    @staticmethod
    def _door_on_space(d: Door, sp: Space) -> bool:
        if d.axis == "y":
            return (abs(d.x - sp.x0) < EPS or abs(d.x - sp.x1) < EPS) and sp.y0 - EPS <= d.y <= sp.y1 + EPS
        return (abs(d.y - sp.y0) < EPS or abs(d.y - sp.y1) < EPS) and sp.x0 - EPS <= d.x <= sp.x1 + EPS

    def _trim_halls(self, lay: Layout) -> None:
        """Company rule 9: hallway only as long as it needs to be; the dead ends become linen closets."""
        for h in [sp for sp in lay.spaces if sp.kind == "hall"]:
            along_y = h.h >= h.w
            lo, hi = (h.y0, h.y1) if along_y else (h.x0, h.x1)
            need = []
            for d in lay.doors:
                if self._door_on_space(d, h) and d.axis == ("y" if along_y else "x"):
                    c = d.y if along_y else d.x
                    need.append((c - d.width / 2 - 0.6, c + d.width / 2 + 0.6))
            for sp in lay.spaces:
                if sp is not h and sp.kind in ("link", "shop_link", "great_room", "shop"):
                    e = shared_edge(sp, h)
                    if e:
                        need.append((e[2], e[3]))
            if not need:
                continue
            n0 = max(lo, min(a for a, _ in need))
            n1 = min(hi, max(b for _, b in need))
            n0 = lo if n0 - lo < 3 else round(n0 * 2) / 2
            n1 = hi if hi - n1 < 3 else round(n1 * 2) / 2
            for a, b in ((lo, n0), (n1, hi)):
                if b - a < 3 - EPS:
                    continue
                if along_y:
                    closet = Space(f"{h.id}_linen{int(a)}", "storage", "Linen", h.x0, a, h.x1, b,
                                   door_side="S" if a >= n1 - EPS else "N", wing=h.wing, column="H")
                else:
                    closet = Space(f"{h.id}_linen{int(a)}", "storage", "Linen", a, h.y0, b, h.y1,
                                   door_side="W" if a >= n1 - EPS else "E", wing=h.wing, column="H")
                lay.spaces.append(closet)
            if along_y:
                h.y0, h.y1 = n0, n1
            else:
                h.x0, h.x1 = n0, n1
            for sp in [x for x in lay.spaces if x.kind == "storage" and x.id.startswith(f"{h.id}_linen")]:
                if not any(d.serves == sp.id for d in lay.doors):
                    self._door_on(lay, sp, h, self.rb.m("storage").door_w, prefer=None, ref=(h.cx, h.cy))

    def _interior_doors(self, lay: Layout) -> None:
        self._fixtures = fixture_geometry(lay, self.rb)
        by_id = {s.id: s for s in lay.spaces}
        great = by_id["great_room"]
        for sp in list(lay.spaces):
            it = getattr(sp, "_item", None)
            if it is None or it.kind in ("link", "shop_link"):
                continue
            m = self.rb.m(sp.kind)
            if it.door == "ensuite":
                partner = by_id[sp._partner]  # type: ignore[attr-defined]
                self._door_on(lay, sp, partner, m.door_w, ref=self._ref_point(lay, partner))
            elif it.door == "great":
                self._door_on(lay, sp, great, m.door_w, ref=(great.cx, great.cy))
            else:
                hall = by_id.get(f"{sp.wing}_hall", great)
                self._door_on(lay, sp, hall, m.door_w)
        # shop access
        if self.shop > 0:
            shop = by_id["shop"]
            ew = self.rb.b("ext_door_w")
            prio = {"laundry_mud": 0, "hall": 2, "shop_link": 3, "great_room": 4}
            cands = []
            for s in lay.spaces:
                e = shared_edge(s, shop) if s.kind in prio else None
                if e and e[3] - e[2] >= ew + 1:
                    cands.append(s)
            if not cands:
                raise Invalid("no_shop_access")
            pick = sorted(cands, key=lambda s: prio[s.kind])[0]
            self._door_on(lay, pick, shop, ew, kind="interior", wall="shop", ref=(shop.cx, 0.0))

    def _exterior_doors(self, lay: Layout) -> None:
        g = lay.space("great_room")
        ew = self.rb.b("ext_door_w")
        dh = self.rb.b("door_height")
        # main entrance (company rule 5): single 3' or double 6', near the side of the living wall (rule 3)
        double = self.req.main_entrance == "double"
        mw = self.rb.b("entry_double_w") if double else self.rb.b("entry_single_w")
        end = self.style.get("entry_end", "center")
        pref = {"low": g.x0 + 2 + mw / 2, "high": g.x1 - 2 - mw / 2}.get(end, g.cx)
        c = _place_on_wall(g.x0, g.x1, mw, pref, self.wall_obstacles(lay, "x", 0.0), margin=0.75)
        if c is None:
            # no gap between posts: frame a header and move the post(s) to the door jambs
            c = _place_on_wall(g.x0, g.x1, mw, pref, [o for o in self.wall_obstacles(lay, "x", 0.0)
                                                      if not self._is_post_obstacle(lay, o, "x", 0.0)], margin=0.75)
            if c is None:
                raise Invalid("front_door")
            self._posts_to_jambs(lay, "x", 0.0, c, mw)
            lay.notes.append("Main entrance gets a framed header; the post moves to the door jamb.")
        lay.doors.append(Door(c, 0.0, "x", mw, "exterior", into=1, serves="great_room", wall="ext", height=dh,
                              leaves=2 if double else 1, hinge=-1 if c < g.cx else 1))
        # back door (only if the kitchen leaves room for it)
        if g.w >= 19.5:
            obs = self.wall_obstacles(lay, "x", self.D)
            for lo, hi, pref in ((g.x0, min(g.x0 + 4.5, g.x1), g.x0 + 2.4), (max(g.x1 - 4.5, g.x0), g.x1, g.x1 - 2.4)):
                c = _place_on_wall(lo, hi, ew, pref, obs, margin=0.4)
                if c is not None:
                    lay.doors.append(Door(c, self.D, "x", ew, "exterior", into=-1, hinge=1 if c < g.cx else -1,
                                          serves="great_room", wall="ext", height=dh))
                    break
        if not any(d.kind == "exterior" and d.serves == "great_room" and d.y == self.D for d in lay.doors):
            for h in [s for s in lay.spaces if s.kind == "hall"]:
                done = False
                for side in lay.exterior_sides(h):
                    if side in ("W", "E"):
                        fx = 0.0 if side == "W" else self.L
                        c = _place_on_wall(h.y0, h.y1, ew, h.cy, self.wall_obstacles(lay, "y", fx), margin=0.25)
                        if c is not None:
                            lay.doors.append(Door(fx, c, "y", ew, "exterior", into=1 if side == "W" else -1, serves=h.id,
                                                  wall="ext", height=dh))
                            done = True
                            break
                if done:
                    break
        if self.shop <= 0:
            return
        # shop overhead doors + man door
        ohw = self.rb.b("overhead_door_w")
        n = self.req.overhead_doors
        x0, x1 = self.living, self.L
        if n:
            if (x1 - x0) >= n * (ohw + 2) + 1:
                axis, fixed, lo, hi = "x", 0.0, x0, x1
            elif self.D >= n * (ohw + 2) + 1:
                axis, fixed, lo, hi = "y", self.L, 0.0, self.D
            else:
                axis, fixed, lo, hi = "x", 0.0, x0, x1
                n = max(1, int((x1 - x0 - 1) // (ohw + 2)))
                if n * (ohw + 2) + 1 > x1 - x0:
                    n = 0
                    lay.notes.append("Shop is too short for an overhead door on the front wall.")
            span = (hi - lo) / max(n, 1)
            for i in range(n):
                c = lo + span * (i + 0.5)
                ohh = self.rb.b("overhead_door_h")
                if axis == "x":
                    lay.doors.append(Door(c, fixed, "x", ohw, "overhead", into=1, serves="shop", wall="ext", height=ohh))
                else:
                    lay.doors.append(Door(fixed, c, "y", ohw, "overhead", into=-1, serves="shop", wall="ext", height=ohh))
                self._posts_to_jambs(lay, axis, fixed, c, ohw)
        # man door: front wall, else end wall
        placed = False
        for axis, fixed, lo, hi in (("x", 0.0, x0, x1), ("y", self.L, 0.0, self.D), ("x", self.D, x0, x1)):
            c = _place_on_wall(lo, hi, ew, lo + 2 + ew / 2, self.wall_obstacles(lay, axis, fixed), margin=0.75)
            if c is not None:
                if axis == "x":
                    lay.doors.append(Door(c, fixed, "x", ew, "exterior", into=1 if fixed == 0 else -1, serves="shop",
                                          wall="ext", height=dh))
                else:
                    lay.doors.append(Door(fixed, c, "y", ew, "exterior", into=-1, serves="shop", wall="ext", height=dh))
                placed = True
                break
        if not placed:
            lay.notes.append("No room for a shop man-door between posts; add one at a framed opening.")

    # -- windows -------------------------------------------------------------
    def _exterior_segments(self, lay: Layout, sp: Space) -> list[tuple[str, float, float, float]]:
        segs = []
        for side in lay.exterior_sides(sp):
            if side == "S":
                segs.append(("x", 0.0, sp.x0, sp.x1))
            elif side == "N":
                segs.append(("x", self.D, sp.x0, sp.x1))
            elif side == "W":
                segs.append(("y", 0.0, sp.y0, sp.y1))
            else:
                segs.append(("y", self.L, sp.y0, sp.y1))
        segs.sort(key=lambda s: s[3] - s[2], reverse=True)
        return segs

    def _seg_side(self, seg) -> str:
        axis, fixed = seg[0], seg[1]
        if axis == "x":
            return "S" if abs(fixed) < EPS else "N"
        return "W" if abs(fixed) < EPS else "E"

    def _windows(self, lay: Layout) -> None:
        """Company rules 4 + 6: standard 3x4 windows, doubles in the primary bedroom, living
        area and kitchen; bedrooms, kitchen, office and living always get windows."""
        ww, wh = self.rb.b("window_w"), self.rb.b("window_h")
        for sp in lay.spaces:
            if sp.kind in ("hall", "link", "shop_link"):
                continue
            if sp.kind == "shop":
                count, units, needs = 2, 1, False
            else:
                m = self.rb.m(sp.kind)
                count, units, needs = m.windows, m.window_units, m.needs_exterior
            segs = self._exterior_segments(lay, sp)
            if not segs:
                if needs:
                    raise Invalid("no_exterior_wall")
                continue
            if count <= 0:
                continue
            width = ww * units
            plan = []  # (segment, preferred position)
            if sp.kind == "great_room":
                ks = OPPOSITE[sp.door_side or "S"]
                kseg = [g for g in segs if self._seg_side(g) == ks]
                lsegs = sorted([g for g in segs if self._seg_side(g) != ks],
                               key=lambda g: (self._seg_side(g) != "S", -(g[3] - g[2])))
                if not kseg or not lsegs:
                    raise Invalid("kitchen_or_living_window")
                gm = self.rb.m("great_room")
                ins, theta = placement(sp, sp.door_side, gm.min_w, gm.min_d, sp.anchor or gm.fixture_anchor,
                                       lay.exterior_sides(sp), self.rb.b("ext_wall"), self.rb.b("int_wall"))
                t = math.radians(theta)
                sx = ins[0] + (gm.min_w / 2) * math.cos(t) - gm.min_d * math.sin(t)
                sy = ins[1] + (gm.min_w / 2) * math.sin(t) + gm.min_d * math.cos(t)
                k = kseg[0]
                plan.append((k, sx if k[0] == "x" else sy))           # over the kitchen sink
                # living windows: front wall first, then the other outside walls
                n_living = max(1, count - 1)
                per_seg = [0] * len(lsegs)
                for i in range(n_living):
                    per_seg[0 if (i < 2 or len(lsegs) == 1) else 1 + (i - 2) % (len(lsegs) - 1)] += 1
                for g, n in zip(lsegs, per_seg):
                    for i in range(n):
                        plan.append((g, g[2] + (g[3] - g[2]) * (i + 1) / (n + 1)))
            else:
                alloc = [0] * len(segs)
                for i in range(count):
                    alloc[i % len(segs)] += 1
                for g, k in zip(segs, alloc):
                    for i in range(k):
                        plan.append((g, g[2] + (g[3] - g[2]) * (i + 1) / (k + 1)))
            placed = 0
            for (axis, fixed, lo, hi), pref in plan:
                c = _place_on_wall(lo, hi, width, pref, self.wall_obstacles(lay, axis, fixed), margin=0.5)
                if c is None:
                    continue
                if axis == "x":
                    lay.windows.append(Window(c, fixed, "x", width, sp.id, height=wh, units=units))
                else:
                    lay.windows.append(Window(fixed, c, "y", width, sp.id, height=wh, units=units))
                placed += 1
            if needs and placed == 0:
                raise Invalid("no_egress_window")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def great_room_score(w: float, d: float, gm) -> float:
    pref_area = gm.pref_w * gm.pref_d
    s = -abs(w * d - pref_area) / pref_area * 6
    ratio = max(w, d) / max(min(w, d), 1)
    if ratio > 1.8:
        s -= (ratio - 1.8) * 4
    if min(w, d) < 18:
        s -= (18 - min(w, d)) * 0.8
    return s

def score_layout(lay: Layout, req: Requirements, rb: Rulebook) -> None:
    br: dict[str, float] = {}
    rooms = [s for s in lay.spaces if s.kind in rb.modules and s.kind != "great_room"]
    # 1. room sizes vs preferred
    dev = 0.0
    for s in rooms:
        if s.kind == "storage":
            continue
        m = rb.m(s.kind)
        w, d = s.local_wd()
        dev += abs(w - m.pref_w) / m.pref_w + abs(d - m.pref_d) / m.pref_d
    br["room_sizes"] = -dev * 1.5
    # 2. great room proportions
    g = lay.space("great_room")
    gm = rb.m("great_room")
    br["great_room"] = great_room_score(g.w, g.h, gm)
    living_area = lay.living_length * lay.width
    circ = sum(s.area for s in lay.spaces if s.kind in ("hall", "link", "shop_link"))
    br["circulation"] = -(circ / living_area) * 45   # company rule 9: fewer walkways
    storage = sum(s.area for s in lay.spaces if s.kind == "storage")
    br["leftover_storage"] = -(storage / living_area) * 30
    # 3. plumbing: wet rooms sharing walls or stacked across the hall
    wet = [s for s in lay.spaces if s.kind in rb.modules and rb.m(s.kind).wet and s.kind != "great_room"]
    wet_pts = 0.0
    for i in range(len(wet)):
        for j in range(i + 1, len(wet)):
            e = shared_edge(wet[i], wet[j])
            if e and e[3] - e[2] >= 2:
                wet_pts += 1.5
            elif wet[i].wing == wet[j].wing and wet[i].column != wet[j].column:
                if min(wet[i].y1, wet[j].y1) - max(wet[i].y0, wet[j].y0) >= 2:
                    wet_pts += 0.75
    for s in wet:
        e = shared_edge(s, g)
        if e and e[3] - e[2] >= 2:
            wet_pts += 0.75
    br["plumbing"] = wet_pts
    # 4. split floor plan
    mb = next((s for s in lay.spaces if s.kind == "master_bedroom"), None)
    beds = [s for s in lay.spaces if s.kind == "bedroom"]
    if mb and beds:
        br["split_plan"] = 4.0 * sum(1 for b in beds if b.wing != mb.wing) / len(beds)
    # 5. adjacency rules from the rulebook
    adj = 0.0
    sp = lay.spaces
    for rule in rb.adjacency:
        for i in range(len(sp)):
            for j in range(len(sp)):
                if i == j:
                    continue
                a, b = sp[i], sp[j]
                if a.kind != rule.room_a or b.kind != rule.room_b:
                    continue
                e = shared_edge(a, b)
                if e and e[3] - e[2] >= 2:
                    adj += rule.weight if rule.relation == "prefer" else -rule.weight
    br["adjacency_rules"] = adj
    # 6. corner bedrooms (windows on two sides)
    br["corner_bedrooms"] = 0.6 * sum(1 for s in lay.spaces
                                       if s.kind in ("bedroom", "master_bedroom") and len(lay.exterior_sides(s)) >= 2)
    # 7. windows actually placed in bedrooms
    br["daylight"] = 0.2 * len(lay.windows)
    # privacy: bedrooms that open straight into the great room
    open_beds = 0
    for d in lay.doors:
        if d.kind != "interior":
            continue
        try:
            room = lay.space(d.serves)
        except KeyError:
            continue
        if room.kind in ("bedroom", "master_bedroom") and room.wing and not any(s.kind == "hall" and s.wing == room.wing for s in lay.spaces):
            open_beds += 1
    br["privacy"] = -0.2 * open_beds  # company rule 2 allows rooms to open straight into the great room
    raw = sum(br.values())
    lay.score_breakdown = {k: round(v, 2) for k, v in br.items()}
    lay.score = round(max(1.0, min(99.0, 60 + raw * 2.2)), 1)


def compute_metrics(lay: Layout, req: Requirements, rb: Rulebook) -> None:
    living_area = lay.living_length * lay.width
    circ = sum(s.area for s in lay.spaces if s.kind in ("hall", "link", "shop_link"))
    g = lay.space("great_room")
    porch = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in lay.porches)
    lay.metrics = {
        "footprint": f"{lay.width:g}' x {lay.length:g}'",
        "living_sqft": round(living_area),
        "shop_sqft": round(lay.shop_length * lay.width),
        "porch_sqft": round(porch),
        "total_under_roof_sqft": round(lay.length * lay.width + porch),
        "bedrooms": sum(1 for s in lay.spaces if s.kind in ("bedroom", "master_bedroom")),
        "full_baths": sum(1 for s in lay.spaces if s.kind in ("full_bath", "master_bath")),
        "half_baths": sum(1 for s in lay.spaces if s.kind == "half_bath"),
        "great_room": f"{g.w:g}' x {g.h:g}'",
        "circulation_pct": round(100 * circ / living_area, 1),
        "interior_wall_lf": round(interior_wall_length(lay)),
        "windows": len(lay.windows),
        "exterior_doors": sum(1 for d in lay.doors if d.kind == "exterior"),
        "interior_doors": sum(1 for d in lay.doors if d.kind == "interior"),
        "overhead_doors": sum(1 for d in lay.doors if d.kind == "overhead"),
        "split_plan": bool(lay.score_breakdown.get("split_plan", 0) > 0),
    }


def _signature(wings: dict[str, WingFit]) -> str:
    parts = []
    for side in ("L", "R", "B"):
        if side in wings:
            wf = wings[side]
            a = "-".join(i.kind for i in wf.a.items)
            b = "-".join(i.kind for i in wf.b.items) if wf.b else ""
            parts.append(f"{side}[{a}|{b}]")
    return " ".join(parts)


def _family(lay: Layout) -> str:
    mb = next(s for s in lay.spaces if s.kind == "master_bedroom")
    sides = "".join(sorted({s.wing for s in lay.spaces if s.wing}))
    halls = "".join(sorted(s.wing for s in lay.spaces if s.kind == "hall"))
    return f"{sides}:{mb.wing}:{halls}"


def _concept(lay: Layout) -> str:
    wings = sorted({s.wing for s in lay.spaces if s.wing and s.kind not in ("storage",)})
    halls = [s for s in lay.spaces if s.kind == "hall"]
    mb = next(s for s in lay.spaces if s.kind == "master_bedroom")
    beds = [s for s in lay.spaces if s.kind == "bedroom"]
    if wings == ["B"]:
        base = "Rear bedroom wing"
    elif len(wings) == 2:
        base = "Split plan" if beds and all(b.wing != mb.wing for b in beds) else "Two-wing plan"
    else:
        base = "Single bedroom wing"
    flow = "open flow, rooms open to the great room" if not halls else (
        "short hallway" if all(min(h.w, h.h) * max(h.w, h.h) < 120 for h in halls) else "private hallway")
    g = lay.space("great_room")
    a = g.anchor or "back-center"
    kitchen = {"back-left": "corner kitchen", "back-right": "corner kitchen"}.get(a, "centered kitchen")
    if g.door_side in ("E", "W"):
        kitchen = "kitchen on the end wall"
    return f"{base} - {flow}, {kitchen}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_layouts(req: Requirements, rb: Optional[Rulebook] = None, count: int = 6, trials: int = 350,
                     seed: Optional[int] = None) -> list[Layout]:
    rb = rb or load_rulebook()
    min_shop = rb.b("min_shop_length")
    if 0 < req.shop_length < min_shop:
        raise LayoutError(f"Shop length must be 0 or at least {min_shop:g} ft.")
    if req.living_length < 24:
        raise LayoutError("Not enough living length left after the shop (need at least 24 ft).")
    base_seed = seed if seed is not None else int(req.fingerprint(), 16)
    # Relaxation ladder: if nothing fits, step down the "nice to haves" one at a time
    # (and tell the customer what changed) instead of returning nothing.
    ladder = [
        (None, {}),
        ("The primary walk-in closet became a reach-in closet so everything fits.", {"walk_in_closet": False}),
        ("The walk-in pantry became a pantry cabinet in the kitchen so everything fits.", {"pantry": False}),
        ("The mudroom was dropped so everything fits (drop zone at the shop door instead).", {"mudroom": False}),
        ("The office was dropped so everything fits.", {"office": False}),
    ]
    all_reasons: Counter = Counter()
    notes: list[str] = []
    current = req
    for step, (note, change) in enumerate(ladder):
        if change:
            if all(getattr(current, k) == v for k, v in change.items()):
                continue
            current = current.model_copy(update=change)
            notes.append(note)
        for extra_flex in range(0, 5 if step == 0 else 1):
            rng = random.Random(base_seed + 7919 * step + extra_flex)
            best, reasons = _search(current, rb, rng, trials * (2 if step == 0 and extra_flex == 0 else 1), extra_flex)
            all_reasons.update(reasons)
            if best:
                extra = list(notes)
                if extra_flex:
                    extra.append(f"The building has more space than the room list needs, so {extra_flex} "
                                 f"flex/bonus room{'s were' if extra_flex > 1 else ' was'} added.")
                return _pick(current, rb, best, count, extra)
            if not reasons.get("great_room_too_wide") or "flex" not in rb.modules:
                break
        if all_reasons.get("great_room_too_wide", 0) > all_reasons.get("great_room_width", 0):
            break  # removing rooms won't help an oversized building
    raise LayoutError(_explain_failure(req, all_reasons))


def _search(req: Requirements, rb: Rulebook, rng: random.Random, trials: int, extra_flex: int):
    gm = rb.m("great_room")
    reasons: Counter = Counter()
    best: dict[str, Layout] = {}
    builder = Builder(req, rb)
    for _ in range(trials):
        plans, style = random_plan(rng, req, rb, extra_flex)
        fits = {}
        ok = True
        for p in plans:
            f = fit_wing(p, req.living_length if p.side == "B" else req.building_width, rb)
            if not f:
                ok = False
                reasons["rooms_do_not_fit_depth"] += 1
                break
            fits[p.side] = f
        if not ok:
            continue
        # choose the best combination of wing options for the great room width
        combos = []
        wide_or_narrow: Counter = Counter()
        sides = list(fits)
        lists = [fits[s] for s in sides]
        if len(lists) == 1:
            pairs = [(f,) for f in lists[0]]
        else:
            pairs = [(f1, f2) for f1 in lists[0] for f2 in lists[1]]
        for combo in pairs:
            if sides == ["B"]:
                gw, gd = req.living_length, req.building_width - combo[0].width
                if not gm.fits(gw, gd):
                    wide_or_narrow["wide" if (gw > gm.max_w or gd > gm.max_d) else "narrow"] += 1
                    continue
            else:
                gw, gd = req.living_length - sum(f.width for f in combo), req.building_width
                if gw < gm.min_w - EPS or gw > gm.max_w + EPS:
                    wide_or_narrow["wide" if gw > gm.max_w else "narrow"] += 1
                    continue
            s = sum(f.score for f in combo) + great_room_score(gw, gd, gm) * 0.75
            combos.append((s, combo))
        if not combos:
            reasons["great_room_too_wide" if wide_or_narrow["wide"] > wide_or_narrow["narrow"] else "great_room_width"] += 1
            continue
        combos.sort(key=lambda c: c[0], reverse=True)
        built = False
        for _, combo in combos[:3]:
            wings = {f.side: f for f in combo}
            sig = _signature(wings)
            try:
                lay = builder.build(wings, style)
            except Invalid as e:
                reasons[str(e)] += 1
                continue
            checks = check_layout(lay, rb, with_estimate=False)
            failed = hard_failures(checks)
            if failed:
                for f in failed:
                    reasons[f"rule {f['id']}"] += 1
                continue
            score_layout(lay, req, rb)
            warns = sum(1 for c in checks if c["status"] == "warn")
            if warns:
                lay.score_breakdown["rule_warnings"] = -3.0 * warns
                lay.score = round(max(1.0, lay.score - 3.0 * 2.2 * warns), 1)
            sig = f"{sig} k{style['kitchen']} e{style['entry_end']} a{'/'.join(str(f.a.depth) for f in combo)}"
            lay.signature = sig
            if sig not in best or best[sig].score < lay.score:
                best[sig] = lay
            built = True
            break
        if not built:
            continue
    return best, reasons


def _pick(req: Requirements, rb: Rulebook, best: dict[str, Layout], count: int, extra_notes: list[str]) -> list[Layout]:
    ranked = sorted(best.values(), key=lambda l: l.score, reverse=True)
    picked: list[Layout] = []
    fam_count: Counter = Counter()
    struct_seen: set[str] = set()
    for lay in ranked:  # diversity first: one option per design family, then fill
        struct = lay.signature.split(" k")[0]
        if struct in struct_seen or fam_count[_family(lay)] >= 1:
            continue
        picked.append(lay)
        struct_seen.add(struct)
        fam_count[_family(lay)] += 1
        if len(picked) >= count:
            break
    for lay in ranked:
        if len(picked) >= count:
            break
        if lay not in picked and lay.signature.split(" k")[0] not in struct_seen:
            picked.append(lay)
            struct_seen.add(lay.signature.split(" k")[0])
    picked.sort(key=lambda l: l.score, reverse=True)
    fp = req.fingerprint()
    from .estimate import estimate_cost  # local import to avoid a cycle
    for i, lay in enumerate(picked, start=1):
        lay.id = f"{fp}-{i}"
        if req.shop_side == "left":
            lay.mirror()
            lay.shop_side = "left"
        lay.notes = extra_notes + lay.notes
        compute_metrics(lay, req, rb)
        lay.estimate = estimate_cost(lay, rb)
        lay.concept = _concept(lay)
        lay.rule_checks = check_layout(lay, rb, with_estimate=True)
        for s in lay.spaces:
            for attr in ("_item", "_partner"):
                if hasattr(s, attr):
                    delattr(s, attr)
    return picked


def _explain_failure(req: Requirements, reasons: Counter) -> str:
    meaningful = Counter({k: v for k, v in reasons.items() if k != "rooms_do_not_fit_depth"})
    top = (meaningful or reasons).most_common(1)[0][0] if reasons else "unknown"
    hints = {
        "great_room_width": "The bedroom wings leave too little room for the kitchen/living area. "
                            "Try a longer building, a shorter shop, or fewer rooms.",
        "great_room_too_wide": "The building is much bigger than the room list needs. Add rooms, a shop, or pick a smaller building.",
        "rooms_do_not_fit_depth": "The rooms don't stack across the building width. Try a different building width or fewer rooms.",
        "no_egress_window": "Some bedrooms can't get an egress window. Try fewer bedrooms or no shop on that side.",
        "no_exterior_wall": "Some bedrooms can't reach an outside wall. Try fewer bedrooms or a longer building.",
        "rule 7": "Bedrooms can't reach the 12' x 12' minimum in this building. Try a bigger building or fewer bedrooms.",
        "rule 8": "Bathrooms can't reach the 5'-4\" minimum width here. Try a bigger building.",
    }
    return (f"No valid layout found for {req.building_width:g}' x {req.building_length:g}' with "
            f"{req.bedrooms} bed / {req.full_baths} bath"
            f"{f' and a {req.shop_length:g} ft shop' if req.shop_length else ''}. "
            + hints.get(top, f"Main blocker: {top}."))
