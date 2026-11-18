"""Budget-level construction estimate from a layout + the Pricing sheet."""
from __future__ import annotations

from typing import Any

from .layout import Layout
from .rules import Rulebook
from .walls import interior_wall_length


def estimate_cost(lay: Layout, rb: Rulebook) -> dict[str, Any]:
    p = rb.pricing
    living = lay.living_length * lay.width
    shop = lay.shop_length * lay.width
    porch = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in lay.porches)
    lines: list[dict[str, Any]] = []

    def add(group: str, item: str, qty: float, unit: str, rate: float):
        if qty <= 0 or rate <= 0:
            return
        lines.append({"group": group, "item": item, "qty": round(qty, 1), "unit": unit, "rate": rate,
                      "amount": round(qty * rate)})

    add("Shell", "Building shell - living", living, "sqft", p.get("shell_living_sqft", 0))
    add("Shell", "Building shell - shop", shop, "sqft", p.get("shell_shop_sqft", 0))
    add("Shell", "Concrete slab", living + shop, "sqft", p.get("slab_sqft", 0))
    add("Shell", "Covered porch", porch, "sqft", p.get("porch_sqft", 0))
    add("Openings", "Exterior man-doors", sum(1 for d in lay.doors if d.kind == "exterior"), "ea", p.get("exterior_door", 0))
    add("Openings", "Overhead doors", sum(1 for d in lay.doors if d.kind == "overhead"), "ea", p.get("overhead_door", 0))
    add("Openings", "Windows", len(lay.windows), "ea", p.get("window", 0))
    add("Interior", "Interior walls", interior_wall_length(lay), "lf", p.get("interior_wall_lf", 0))
    add("Interior", "Interior doors", sum(1 for d in lay.doors if d.kind == "interior"), "ea", p.get("interior_door", 0))
    # room modules: finishes + fixtures
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
        "disclaimer": "Budget-level estimate from placeholder unit rates in the rulebook. Not a quote.",
    }
