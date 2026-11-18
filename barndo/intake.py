"""Customer intake: turn a free-text description into Requirements.

Uses Claude (structured output) when ANTHROPIC_API_KEY (or another Anthropic
credential) is configured, and a rule-based parser otherwise. Either way the
result is a validated Requirements object - the AI never draws geometry, it only
fills in the form that the deterministic layout engine consumes.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .config import AI_MODEL, COMPANY_NAME
from .requirements import Requirements

log = logging.getLogger(__name__)


class IntakeExtraction(BaseModel):
    """Fields the AI fills from the customer's words. null = not mentioned."""
    building_width: Optional[float] = Field(None, description="Building width/depth in feet, e.g. 40 for a 40x60")
    building_length: Optional[float] = Field(None, description="Building length in feet, e.g. 60 for a 40x60")
    bedrooms: Optional[int] = Field(None, description="Total bedrooms including primary")
    full_baths: Optional[int] = None
    half_baths: Optional[int] = None
    office: Optional[bool] = None
    laundry: Optional[bool] = None
    pantry: Optional[bool] = None
    mudroom: Optional[bool] = None
    walk_in_closet: Optional[bool] = None
    shop_length: Optional[float] = Field(None, description="Feet of building length used as shop/garage, 0 for none")
    shop_side: Optional[Literal["left", "right"]] = None
    overhead_doors: Optional[int] = None
    front_porch_depth: Optional[float] = None
    back_porch_depth: Optional[float] = None
    budget: Optional[float] = Field(None, description="Total budget in US dollars")
    customer_name: Optional[str] = None
    notes: Optional[str] = Field(None, description="Wishes that don't map to a field (finishes, style, views, etc.)")
    assumptions: list[str] = Field(default_factory=list, description="Short notes on anything you inferred")
    questions: list[str] = Field(default_factory=list, description="Up to 3 short follow-up questions for missing key info")


SYSTEM_PROMPT = f"""You are the intake assistant for {COMPANY_NAME}, a company that designs barndominiums
(steel / post-frame buildings with living quarters and often a shop or garage under the same roof).

Read the customer's message and fill in the requirement fields. Rules:
- Only set a field when the customer said it or it clearly follows from what they said; otherwise leave it null.
- "40x60" style sizes: the first number is the width (gable span, usually 30-60 ft), the second the length.
  If they give total square footage instead, leave the size null and mention it in assumptions.
- A shop or garage takes the full building width; shop_length is how many feet of building length it uses.
  If they want a shop but give no size, infer a reasonable length (20-30 ft) and say so in assumptions.
  If they give the shop as square feet, convert using the building width when known.
- "2.5 baths" means full_baths=2 and half_baths=1.
- Porch depth: typical covered porches are 8-12 ft deep. "Wraparound" porch -> front porch 10 and note it.
- Keep notes short and factual. Ask at most 3 follow-up questions, only about things that change the layout
  (size, bedrooms, bathrooms, shop).
"""


def _client():
    try:
        import anthropic
    except ImportError:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")):
        return None
    try:
        return anthropic.Anthropic()
    except Exception:  # noqa: BLE001
        return None


def ai_available() -> bool:
    return _client() is not None


def extract_with_ai(text: str) -> IntakeExtraction | None:
    client = _client()
    if client is None:
        return None
    import anthropic

    try:
        resp = client.beta.messages.parse(
            model=AI_MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            output_format=IntakeExtraction,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIStatusError as exc:
        log.warning("AI intake failed (%s): %s", exc.status_code, exc)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("AI intake connection error: %s", exc)
        return None
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return None
    return resp.parsed_output


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "single": 1, "double": 2}


def _n(tok: str) -> float:
    tok = tok.lower()
    return float(_NUM.get(tok, tok))


def extract_with_rules(text: str) -> IntakeExtraction:
    t = text.lower().replace(",", "")
    out = IntakeExtraction()
    num = r"(\d+(?:\.\d+)?|one|two|three|four|five|six)"
    m = re.search(r"(\d{2,3})\s*(?:'|ft|feet)?\s*(?:x|by|×)\s*(\d{2,3})", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        out.building_width, out.building_length = min(a, b), max(a, b)
    m = re.search(num + r"\s*[- ]?(?:bed|br\b|bdr|bedroom)", t)
    if m:
        out.bedrooms = int(_n(m.group(1)))
    m = re.search(num + r"\s*[- ]?(?:bath|ba\b|bathroom)", t)
    if m:
        v = _n(m.group(1))
        out.full_baths = int(v)
        if v - int(v) >= 0.5:
            out.half_baths = 1
    if re.search(r"half[- ]?bath|powder room", t):
        out.half_baths = max(out.half_baths or 0, 1)
    for word, field in (("office", "office"), ("study", "office"), ("pantry", "pantry"), ("mud ?room", "mudroom"),
                        ("laundry", "laundry")):
        if re.search(word, t):
            setattr(out, field, True)
    if re.search(r"no (walk[- ]in|wic)", t):
        out.walk_in_closet = False
    m = re.search(r"(\d{2,3})\s*(?:'|ft|feet)?\s*(?:x|by)\s*(\d{2,3})\s*(?:ft\s*)?(?:shop|garage)", t)
    if m and out.building_width:
        dims = sorted((float(m.group(1)), float(m.group(2))))
        out.shop_length = dims[0] if dims[1] >= out.building_width - 1 else dims[0]
    else:
        m = re.search(r"(\d{2,3})\s*(?:'|ft|foot|feet)?\s*(?:long\s*)?(?:shop|garage)", t)
        if m:
            out.shop_length = float(m.group(1))
        else:
            m = re.search(r"(\d{3,4})\s*(?:sq\.?\s*ft|sf|square feet)\s*(?:of\s*)?(?:shop|garage)", t)
            if m:
                w = out.building_width or 40
                out.shop_length = round(float(m.group(1)) / w)
            elif re.search(r"\b(shop|garage)\b", t) and not re.search(r"no (shop|garage)", t):
                out.shop_length = 24
                out.assumptions.append("Shop size not given - assumed 24 ft of building length.")
    if re.search(r"(\d|one|two|three)\s*(?:overhead|roll[- ]?up|garage) doors?", t):
        m = re.search(r"(\d|one|two|three)\s*(?:overhead|roll[- ]?up|garage) doors?", t)
        out.overhead_doors = int(_n(m.group(1)))
    if "wrap" in t and "porch" in t:
        out.front_porch_depth = 10
        out.assumptions.append("Wraparound porch drawn as a 10 ft front porch; wrap the sides in design development.")
    else:
        m = re.search(r"(\d{1,2})\s*(?:'|ft|foot|feet)?\s*(?:deep\s*)?(?:front )?porch", t)
        if m:
            out.front_porch_depth = float(m.group(1))
        elif "front porch" in t or re.search(r"\bporch\b", t):
            out.front_porch_depth = 10
        if "back porch" in t or "rear porch" in t or "patio" in t:
            out.back_porch_depth = 10
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)\s*(k|m|million)?", t) or re.search(r"(\d+(?:\.\d+)?)\s*(k|m)\b\s*budget", t)
    if m:
        v = float(m.group(1))
        unit = (m.group(2) or "").lower()
        v *= 1000 if unit == "k" else 1_000_000 if unit in ("m", "million") else 1
        if v >= 20000:
            out.budget = v
    if out.building_width is None:
        m = re.search(r"(\d{3,4})\s*(?:sq\.?\s*ft|sf|square feet)", t)
        if m:
            sf = float(m.group(1))
            out.assumptions.append(f"{sf:g} sq ft of living space requested - suggested size based on a 40 ft wide building.")
            out.building_width = 40
            out.building_length = round(sf / 40 / 10) * 10 + (out.shop_length or 0)
    if out.bedrooms is None:
        out.questions.append("How many bedrooms do you need?")
    if out.full_baths is None:
        out.questions.append("How many bathrooms?")
    if out.building_width is None:
        out.questions.append("Do you have a building size in mind (for example 40x60)?")
    return out


def merge(base: Requirements, ext: IntakeExtraction) -> Requirements:
    data = base.model_dump()
    for k, v in ext.model_dump(exclude={"assumptions", "questions"}).items():
        if v is not None and k in data:
            data[k] = v
    if data["half_baths"] is None:
        data["half_baths"] = 0
    # keep things inside the engine's limits
    data["building_width"] = min(max(float(data["building_width"]), 24), 80)
    data["building_length"] = min(max(float(data["building_length"]), 30), 200)
    data["bedrooms"] = min(max(int(data["bedrooms"]), 1), 6)
    data["full_baths"] = min(max(int(data["full_baths"]), 1), 5)
    data["half_baths"] = min(max(int(data["half_baths"]), 0), 2)
    data["shop_length"] = min(max(float(data["shop_length"]), 0), data["building_length"] - 24)
    return Requirements(**data)


def intake(text: str, base: Requirements | None = None) -> dict:
    base = base or Requirements()
    ext = extract_with_ai(text)
    engine = "ai"
    if ext is None:
        ext = extract_with_rules(text)
        engine = "rules"
    req = merge(base, ext)
    if req.shop_length > 0 and req.living_length < 24:
        req = req.model_copy(update={"building_length": req.shop_length + 30})
        ext.assumptions.append("Building lengthened so the living area is at least 30 ft long.")
    return {"requirements": req.model_dump(), "assumptions": ext.assumptions, "questions": ext.questions[:3],
            "engine": engine}
