"""Company rules: checks every plan must pass before it is shown.

Rules live in the "Company Rules" sheet of the rulebook. Each row names a `check`
(one of the functions registered below), the rooms it `applies_to`, a `value`,
and a severity: `hard` rules reject a plan, `soft` rules only flag it.

Adding a rule
-------------
* Most new rules are just a new row that reuses a check type, e.g.
    13 | Office at least 10x10 | min_clear_size | office | 10x10 | hard | Y
* If a rule needs new logic, add a function decorated with @check("name") here
  and use that name in the sheet.

Check types: required_fixtures, no_unneeded_hallway, doors_near_corner,
window_standard, door_standard, laundry_mud_and_windows, must_have_window,
min_clear_size, min_clear_width, max_circulation_pct, not_adjacent, must_be_adjacent,
estimate_uses_eave_and_slope, building_standard, wall_thickness.
"""
from __future__ import annotations

from typing import Any, Callable

from .layout import EPS, OPPOSITE, Layout, Space, clear_dims, fmt_ft, shared_edge
from .module_library import module_fixtures
from .rules import CompanyRule, Rulebook

CHECKS: dict[str, Callable[[Layout, Rulebook, CompanyRule], tuple[bool, str]]] = {}
NEEDS_ESTIMATE = {"estimate_uses_eave_and_slope"}


def check(name: str):
    def deco(fn):
        CHECKS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pair(value: Any) -> tuple[float, float]:
    txt = str(value).lower().replace("'", "").replace(" ", "")
    if "x" in txt:
        a, b = txt.split("x", 1)
        return float(a), float(b)
    v = float(txt)
    return v, v


def _kv(value: Any) -> dict[str, float]:
    out = {}
    for part in str(value).split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = float(v)
    return out


def _clear(lay: Layout, rb: Rulebook, s: Space) -> tuple[float, float]:
    return clear_dims(lay, s, rb.b("ext_wall"), rb.b("int_wall"))


def _kitchen_side(lay: Layout) -> str | None:
    g = next((s for s in lay.spaces if s.kind == "great_room"), None)
    return OPPOSITE.get(g.door_side or "S") if g else None


def _window_side(lay: Layout, s: Space, w) -> str:
    if w.axis == "x":
        return "S" if abs(w.y - s.y0) < EPS else "N"
    return "W" if abs(w.x - s.x0) < EPS else "E"


def _targets(lay: Layout, kinds: list[str]):
    """Yield (label, space, window filter) for room kinds, incl. virtual 'kitchen' / 'living'."""
    ks = _kitchen_side(lay)
    for s in lay.spaces:
        if s.kind in kinds:
            yield s.name or s.kind, s, None
        if s.kind == "great_room":
            if "kitchen" in kinds:
                yield "Kitchen", s, (lambda w, s=s: _window_side(lay, s, w) == ks)
            if "living" in kinds:
                yield "Living area", s, (lambda w, s=s: _window_side(lay, s, w) != ks)


def _windows_of(lay: Layout, s: Space, flt) -> list:
    return [w for w in lay.windows if w.serves == s.id and (flt is None or flt(w))]


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
@check("required_fixtures")
def _required_fixtures(lay, rb, rule):
    need = {x.strip().lower() for x in str(rule.value).split(",") if x.strip()}
    problems = []
    for kind in rule.applies_to:
        if kind not in rb.modules or not any(s.kind == kind for s in lay.spaces):
            continue
        have = module_fixtures(rb.m(kind).dxf_path)
        missing = need - have
        if missing:
            problems.append(f"{rb.m(kind).name} drawing is missing: {', '.join(sorted(missing))}")
    return (not problems, "; ".join(problems) or f"Every full bath has {', '.join(sorted(need))}")


@check("no_unneeded_hallway")
def _no_unneeded_hallway(lay, rb, rule):
    great = next(s for s in lay.spaces if s.kind == "great_room")
    link_w = rb.b("link_width")
    problems = []
    for h in [s for s in lay.spaces if s.kind == "hall"]:
        e = shared_edge(h, great)
        if e and e[3] - e[2] > link_w + 0.5:
            problems.append("a hallway runs along the open great room - rooms should open straight into it")
        served = [d for d in lay.doors if d.kind == "interior" and _door_touches(d, h)]
        if not served:
            problems.append("a hallway serves no rooms")
    return (not problems, "; ".join(dict.fromkeys(problems)) or "Hallways only where rooms can't open to the open space")


def _door_touches(d, s: Space) -> bool:
    if d.axis == "y":
        return (abs(d.x - s.x0) < EPS or abs(d.x - s.x1) < EPS) and s.y0 - EPS <= d.y <= s.y1 + EPS
    return (abs(d.y - s.y0) < EPS or abs(d.y - s.y1) < EPS) and s.x0 - EPS <= d.x <= s.x1 + EPS


@check("doors_near_corner")
def _doors_near_corner(lay, rb, rule):
    limit = float(rule.value or 1.0)
    scope = set(rule.applies_to or ["interior"])
    problems = []
    for d in lay.doors:
        if d.kind not in ("interior", "exterior") or d.kind not in scope:
            continue
        try:
            room = lay.space(d.serves)
        except KeyError:
            continue
        lo, hi = (room.y0, room.y1) if d.axis == "y" else (room.x0, room.x1)
        c = d.y if d.axis == "y" else d.x
        dist = min(c - d.width / 2 - lo, hi - (c + d.width / 2))
        if dist > limit + 0.05:
            problems.append(f"{room.name or room.kind} door is {fmt_ft(dist)} from the corner")
    return (not problems, "; ".join(problems) or f"All doors within {fmt_ft(limit)} of a wall corner")


@check("window_standard")
def _window_standard(lay, rb, rule):
    ww, wh = _pair(rule.value or f"{rb.b('window_w')}x{rb.b('window_h')}")
    problems = []
    for w in lay.windows:
        if abs(w.height - wh) > 0.01 or abs(w.width - ww * w.units) > 0.01:
            problems.append(f"window {fmt_ft(w.width)} x {fmt_ft(w.height)} is not standard")
    for label, s, flt in _targets(lay, rule.applies_to):
        for w in _windows_of(lay, s, flt):
            if w.units < 2:
                problems.append(f"{label} needs double windows")
                break
    return (not problems, "; ".join(dict.fromkeys(problems)) or
            f"All windows {ww:g}x{wh:g}; doubles in {', '.join(rule.applies_to)}")


@check("door_standard")
def _door_standard(lay, rb, rule):
    h = float(rule.value or rb.b("door_height"))
    allowed = {rb.b("entry_single_w"), rb.b("entry_double_w")}
    problems = [f"door height {fmt_ft(d.height)}" for d in lay.doors if d.kind in ("interior", "exterior") and abs(d.height - h) > 0.01]
    main = [d for d in lay.doors if d.kind == "exterior" and d.serves == "great_room" and d.axis == "x" and abs(d.y) < EPS]
    if not main:
        problems.append("no main entrance")
    for d in main:
        if not any(abs(d.width - a) < 0.01 for a in allowed):
            problems.append(f"main entrance is {fmt_ft(d.width)} wide")
    return (not problems, "; ".join(dict.fromkeys(problems)) or
            f"Doors {fmt_ft(h)} high; main entrance {fmt_ft(main[0].width) if main else '-'}")


@check("laundry_mud_and_windows")
def _laundry_mud_and_windows(lay, rb, rule):
    problems = []
    if any(s.kind in ("laundry", "mudroom") for s in lay.spaces):
        problems.append("laundry and mudroom are separate rooms")
    ok, msg = _must_have_window(lay, rb, rule)
    if not ok:
        problems.append(msg)
    return (not problems, "; ".join(problems) or "Laundry/mudroom combined; all required rooms have windows")


@check("must_have_window")
def _must_have_window(lay, rb, rule):
    missing = [label for label, s, flt in _targets(lay, rule.applies_to) if not _windows_of(lay, s, flt)]
    return (not missing, f"no window in: {', '.join(missing)}" if missing else "Required rooms have windows")


@check("min_clear_size")
def _min_clear_size(lay, rb, rule):
    a, b = sorted(_pair(rule.value))
    problems = []
    for s in lay.spaces:
        if s.kind in rule.applies_to:
            cw, ch = sorted(_clear(lay, rb, s))
            if cw < a - 0.01 or ch < b - 0.01:
                problems.append(f"{s.name} is {fmt_ft(cw)} x {fmt_ft(ch)}")
    return (not problems, "; ".join(problems) or f"All at least {fmt_ft(a)} x {fmt_ft(b)} clear")


@check("min_clear_width")
def _min_clear_width(lay, rb, rule):
    v = float(rule.value)
    problems = [f"{s.name} is {fmt_ft(min(_clear(lay, rb, s)))} wide" for s in lay.spaces
                if s.kind in rule.applies_to and min(_clear(lay, rb, s)) < v - 0.01]
    return (not problems, "; ".join(problems) or f"All at least {fmt_ft(v)} wide clear")


@check("max_circulation_pct")
def _max_circulation(lay, rb, rule):
    living = lay.living_length * lay.width
    circ = sum(s.area for s in lay.spaces if s.kind in ("hall", "link", "shop_link"))
    pct = 100 * circ / living if living else 0
    v = float(rule.value or 12)
    return (pct <= v + 1e-6, f"Hallways are {pct:.1f}% of the living area (target {v:g}% or less)")


@check("not_adjacent")
def _not_adjacent(lay, rb, rule):
    a, b = (rule.applies_to + ["", ""])[:2]
    bad = [f"{x.name or x.kind} touches {y.name or y.kind}" for x in lay.spaces for y in lay.spaces
           if x.kind == a and y.kind == b and (e := shared_edge(x, y)) and e[3] - e[2] >= 1]
    return (not bad, "; ".join(bad) or f"{a} never next to {b}")


@check("must_be_adjacent")
def _must_be_adjacent(lay, rb, rule):
    a, b = (rule.applies_to + ["", ""])[:2]
    xs = [s for s in lay.spaces if s.kind == a]
    bad = [x.name or x.kind for x in xs if not any(
        (e := shared_edge(x, y)) and e[3] - e[2] >= 2 for y in lay.spaces if y.kind == b)]
    return (not bad, f"not next to {b}: {', '.join(bad)}" if bad else f"{a} next to {b}")


@check("estimate_uses_eave_and_slope")
def _estimate_uses(lay, rb, rule):
    est = lay.estimate or {}
    b = est.get("building", {})
    ok = bool(b.get("eave_height")) and bool(b.get("roof_pitch")) and \
        any(l["item"].startswith("Roof") for l in est.get("lines", [])) and \
        any(l["item"].startswith("Exterior walls") for l in est.get("lines", []))
    return (ok, f"Estimate uses {b.get('eave_height', '?'):g}' eave and {b.get('roof_pitch', '?'):g}:12 slope "
                f"(wall area {b.get('wall_area_sqft', 0):,} sf, roof area {b.get('roof_area_sqft', 0):,} sf)"
            if ok else "estimate does not include eave height and slope")


@check("building_standard")
def _building_standard(lay, rb, rule):
    std = _kv(rule.value) or {"eave_height": rb.b("eave_height"), "roof_pitch": rb.b("roof_pitch")}
    req = lay.requirements
    diffs = [f"{k.replace('_', ' ')} {req.get(k):g} (standard {v:g})" for k, v in std.items()
             if req.get(k) is not None and abs(float(req[k]) - v) > 1e-6]
    return (not diffs, "Customer changed: " + "; ".join(diffs) if diffs else
            f"{std.get('eave_height', 12):g}' eave, {std.get('roof_pitch', 4):g}:12 slope")


@check("wall_thickness")
def _wall_thickness(lay, rb, rule):
    std = _kv(rule.value)
    have = {"ext": rb.b("ext_wall"), "int": rb.b("int_wall")}
    bad = [f"{k} wall is {have[k] * 12:.1f}\" (should be {v * 12:.0f}\")" for k, v in std.items()
           if k in have and abs(have[k] - v) > 0.01]
    return (not bad, "; ".join(bad) or f"Exterior {have['ext'] * 12:.0f}\", interior {have['int'] * 12:.0f}\"")


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------
def check_layout(lay: Layout, rb: Rulebook, with_estimate: bool = True) -> list[dict[str, Any]]:
    results = []
    for rule in rb.rules:
        if not rule.enabled:
            continue
        if not with_estimate and rule.check in NEEDS_ESTIMATE:
            continue
        fn = CHECKS.get(rule.check)
        if fn is None:
            results.append({"id": rule.id, "rule": rule.rule, "status": "unknown", "severity": rule.severity,
                            "detail": f"Unknown check type '{rule.check}'"})
            continue
        try:
            ok, detail = fn(lay, rb, rule)
        except Exception as exc:  # noqa: BLE001 - a broken rule row must not crash the app
            ok, detail = False, f"rule error: {exc}"
        status = "pass" if ok else ("fail" if rule.severity == "hard" else "warn")
        results.append({"id": rule.id, "rule": rule.rule, "status": status, "severity": rule.severity, "detail": detail})
    return results


def hard_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if r["status"] == "fail"]
