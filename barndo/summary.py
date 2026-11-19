"""Customer-facing description of a layout (template, optionally AI-polished)."""
from __future__ import annotations

import json
import logging

from .config import AI_MODEL, COMPANY_NAME
from .intake import _client
from .layout import Layout, fmt_ft

log = logging.getLogger(__name__)


def template_summary(lay: Layout) -> str:
    m = lay.metrics
    g = lay.space("great_room")
    mb = next(s for s in lay.spaces if s.kind == "master_bedroom")
    beds = [s for s in lay.spaces if s.kind == "bedroom"]
    parts = [
        f"A {m['footprint']} barndominium with {m['living_sqft']:,} sq ft of living space"
        + (f" and a {m['shop_sqft']:,} sq ft shop" if m["shop_sqft"] else "") + ".",
        f"The open kitchen, dining and living area is {fmt_ft(g.w)} x {fmt_ft(g.h)} with the kitchen along the back wall "
        "and an island facing the living space.",
    ]
    if m.get("split_plan"):
        parts.append("It is a split floor plan: the primary suite sits on the opposite side of the house from the other "
                     "bedrooms for privacy.")
    suite = "with its own bath" + (" and walk-in closet" if any(s.kind == "master_wic" for s in lay.spaces) else "")
    parts.append(f"The primary bedroom ({fmt_ft(mb.w)} x {fmt_ft(mb.h)}) comes {suite}.")
    if beds:
        parts.append(f"{len(beds)} more bedroom{'s' if len(beds) > 1 else ''} "
                     f"{'share' if len(beds) > 1 else 'uses'} {m['full_baths'] - 1 or 'the'} bath"
                     f"{'s' if m['full_baths'] - 1 > 1 else ''}.")
    extras = [s.name.lower() for s in lay.spaces if s.kind in ("laundry_mud", "pantry", "office", "half_bath", "flex")]
    if extras:
        parts.append("Also included: " + ", ".join(dict.fromkeys(extras)) + ".")
    if lay.shop_length:
        oh = m.get("overhead_doors", 0)
        parts.append(f"The shop has {oh} overhead door{'s' if oh != 1 else ''} and a walk-in door, with direct access "
                     "into the house.")
    b = lay.estimate.get("building", {})
    if b:
        parts.append(f"The building has a {b['eave_height']:g} ft eave and a {b['roof_pitch']:g}:12 roof.")
    if m["porch_sqft"]:
        parts.append(f"Covered porch: {m['porch_sqft']:,} sq ft.")
    parts.extend(lay.notes)
    return " ".join(parts)


def ai_summary(lay: Layout) -> str | None:
    client = _client()
    if client is None:
        return None
    import anthropic

    facts = {
        "metrics": lay.metrics,
        "rooms": [{"name": s.name, "w_ft": round(s.w, 1), "d_ft": round(s.h, 1), "wing": s.wing}
                  for s in lay.rooms() if s.kind != "storage"],
        "notes": lay.notes,
        "estimate_total": lay.estimate.get("total"),
    }
    try:
        resp = client.beta.messages.create(
            model=AI_MODEL,
            max_tokens=2000,
            system=(f"You write short, warm, factual floor plan descriptions for {COMPANY_NAME}'s barndominium customers. "
                    "Use only the facts given. 90-140 words, plain prose, no headings, no prices, no promises about "
                    "permits or engineering."),
            messages=[{"role": "user", "content": "Describe this plan:\n" + json.dumps(facts)}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.warning("AI summary failed: %s", exc)
        return None
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or None


def summarize(lay: Layout, use_ai: bool = True) -> dict:
    if use_ai:
        txt = ai_summary(lay)
        if txt:
            return {"text": txt, "engine": "ai"}
    return {"text": template_summary(lay), "engine": "template"}
