"""Budget-level construction estimate from a layout + the Pricing sheet.

Company rules 10 + 11: the building shell is priced from real surface areas, which
depend on the eave height and roof slope (standard 12' eave, 4:12 slope):

* exterior wall area = perimeter x eave height + the two gable triangles
* roof area          = (width + 2 overhang) x (length + 2 overhang) x slope factor
                       slope factor = sqrt(1 + (pitch/12)^2)
"""
from __future__ import annotations

import math
from typing import Any

from .layout import Layout
from .rules import Rulebook
from .walls import interior_wall_length


def building_geometry(lay: Layout, rb: Rulebook) -> dict[str, float]:
    req = lay.requirements
    W, L = lay.width, lay.length
    eave = float(req.get("eave_height") or rb.b("eave_height"))
    pitch = float(req.get("roof_pitch") or rb.b("roof_pitch"))
    ovh = rb.b("roof_overhang") if "roof_overhang" in rb.building else 1.0
    rise = (W / 2) * pitch / 12
    slope_factor = math.sqrt(1 + (pitch / 12) ** 2)
    gable_area = 2 * (0.5 * W * rise)
    wall_area = 2 * (W + L) * eave + gable_area
    roof_area = (W + 2 * ovh) * (L + 2 * ovh) * slope_factor
    living_frac = lay.living_length / L if L else 1.0
    # surfaces around the living area (for insulation): its share of the long walls + roof,
    # the end wall(s) it owns, and the shop separation wall.
    living_walls = 2 * lay.living_length * eave + (W * eave + gable_area / 2) * (1 if lay.shop_length else 2)
    if lay.shop_length:
        living_walls += W * eave + gable_area / 2  # separation wall up to the roof
    return {
        "eave_height": eave,
        "roof_pitch": pitch,
        "ridge_height": round(eave + rise, 2),
        "slope_factor": round(slope_factor, 4),
        "wall_area_sqft": round(wall_area),
        "roof_area_sqft": round(roof_area),
        "living_envelope_sqft": round(living_walls + roof_area * living_frac),
    }


def estimate_cost(lay: Layout, rb: Rulebook) -> dict[str, Any]:
    p = rb.pricing
    living = lay.living_length * lay.width
    shop = lay.shop_length * lay.width
    porch = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in lay.porches)
    geo = building_geometry(lay, rb)
    lines: list[dict[str, Any]] = []

    def add(group: str, item: str, qty: float, unit: str, rate: float):
        if qty <= 0 or rate <= 0:
            return
        lines.append({"group": group, "item": item, "qty": round(qty, 1), "unit": unit, "rate": rate,
                      "amount": round(qty * rate)})

    add("Shell", "Structure (posts / frames)", living + shop, "sqft", p.get("structure_sqft", 0))
    add("Shell", f"Exterior walls - {geo['eave_height']:g}' eave incl. gables", geo["wall_area_sqft"], "sqft",
        p.get("wall_cladding_sqft", 0))
    add("Shell", f"Roof - {geo['roof_pitch']:g}:12 slope", geo["roof_area_sqft"], "sqft", p.get("roof_sqft", 0))
    add("Shell", "Insulation around living area", geo["living_envelope_sqft"], "sqft", p.get("insulation_sqft", 0))
    # older rulebooks priced the shell per floor sqft - still honoured if present
    add("Shell", "Building shell - living", living, "sqft", p.get("shell_living_sqft", 0))
    add("Shell", "Building shell - shop", shop, "sqft", p.get("shell_shop_sqft", 0))
    add("Shell", "Concrete slab", living + shop, "sqft", p.get("slab_sqft", 0))
    add("Shell", "Covered porch", porch, "sqft", p.get("porch_sqft", 0))
    singles = [d for d in lay.doors if d.kind == "exterior" and d.leaves == 1]
    doubles = [d for d in lay.doors if d.kind == "exterior" and d.leaves == 2]
    add("Openings", "Exterior doors (single)", len(singles), "ea", p.get("exterior_door", 0))
    add("Openings", "Exterior doors (double)", len(doubles), "ea", p.get("exterior_door_double", p.get("exterior_door", 0) * 2))
    add("Openings", "Overhead doors", sum(1 for d in lay.doors if d.kind == "overhead"), "ea", p.get("overhead_door", 0))
    add("Openings", "Windows 3x4 (a double counts 2)", sum(w.units for w in lay.windows), "ea", p.get("window", 0))
    add("Interior", "Interior walls", interior_wall_length(lay), "lf", p.get("interior_wall_lf", 0))
    add("Interior", "Interior doors", sum(1 for d in lay.doors if d.kind == "interior"), "ea", p.get("interior_door", 0))
    for s in lay.spaces:
        if s.kind not in rb.modules:
            continue
        m = rb.m(s.kind)
        add("Rooms", f"{s.name or m.name} finishes", s.area, "sqft", m.finish_cost_sqft)
        add("Rooms", f"{s.name or m.name} fixtures / cabinets", 1, "ls", m.fixture_cost)
    add("MEP", "Plumbing / electrical / HVAC - living", living, "sqft", p.get("mep_living_sqft", 0))
    add("MEP", "Electrical / lighting - shop", shop, "sqft", p.get("mep_shop_sqft", 0))
    subtotal = sum(l["amount"] for l in lines)
    cont = round(subtotal * p.get("contingency_pct", 0) / 100)
    total = subtotal + cont
    groups: dict[str, int] = {}
    for l in lines:
        groups[l["group"]] = groups.get(l["group"], 0) + l["amount"]
    budget = lay.requirements.get("budget")
    return {
        "lines": lines,
        "groups": groups,
        "subtotal": subtotal,
        "contingency": cont,
        "total": total,
        "per_living_sqft": round(total / living) if living else None,
        "budget": budget,
        "within_budget": (total <= budget) if budget else None,
        "building": geo,
        "disclaimer": "Budget-level estimate from placeholder unit rates in the rulebook. Not a quote.",
    }
