"""FastAPI web app: configurator, AI intake, layouts, downloads, proposals, leads."""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import date
from html import escape
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import leads as leads_mod
from .config import ADMIN_TOKEN, COMPANY_NAME, OUTPUT_DIR, RULEBOOK_PATH, WEB_DIR
from .intake import ai_available, intake
from .layout import Layout, clear_dims, fmt_ft, layout_from_dict
from .module_library import create_placeholder_library, validate_library
from .render_dxf import convert_to_dwg, oda_available, write_dxf
from .render_svg import render_svg
from .requirements import Requirements
from .rules import load_rulebook, write_default_rulebook
from .solver import LayoutError, generate_layouts
from .summary import summarize

log = logging.getLogger("barndo")
app = FastAPI(title=f"{COMPANY_NAME} Barndo Planner", version="1.0")

write_default_rulebook()  # creates rules/barndo_rules.xlsx the first time
RB = load_rulebook()
create_placeholder_library(RB)  # creates missing placeholder module drawings only
LAYOUT_DIR = OUTPUT_DIR / "layouts"
LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
_cache: "OrderedDict[str, Layout]" = OrderedDict()


def _store(lay: Layout) -> None:
    _cache[lay.id] = lay
    _cache.move_to_end(lay.id)
    while len(_cache) > 300:
        _cache.popitem(last=False)
    (LAYOUT_DIR / f"{lay.id}.json").write_text(json.dumps(lay.to_dict()))


def _get(layout_id: str) -> Layout:
    if layout_id in _cache:
        return _cache[layout_id]
    if not all(c.isalnum() or c == "-" for c in layout_id):
        raise HTTPException(404, "Unknown layout")
    f = LAYOUT_DIR / f"{layout_id}.json"
    if not f.exists():
        raise HTTPException(404, "Unknown layout - generate it again")
    lay = layout_from_dict(json.loads(f.read_text()))
    _cache[layout_id] = lay
    return lay


def _check_admin(token: Optional[str]) -> None:
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(403, "Admin token required (set BARNDO_ADMIN_TOKEN)")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class IntakeIn(BaseModel):
    text: str = Field(..., min_length=2, max_length=4000)
    requirements: Optional[Requirements] = None


class LeadIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    phone: str = Field("", max_length=40)
    message: str = Field("", max_length=2000)
    layout_id: str = Field("", max_length=40)


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "company": COMPANY_NAME,
        "footprints": RB.footprints,
        "ai": ai_available(),
        "dwg": oda_available(),
        "defaults": Requirements().model_dump(),
        "min_shop_length": RB.b("min_shop_length"),
    }


@app.post("/api/intake")
def api_intake(body: IntakeIn) -> dict[str, Any]:
    return intake(body.text, body.requirements)


@app.post("/api/layouts")
def api_layouts(req: Requirements, count: int = Query(6, ge=1, le=12)) -> dict[str, Any]:
    try:
        layouts = generate_layouts(req, RB, count=count)
    except LayoutError as exc:
        raise HTTPException(422, str(exc)) from exc
    out = []
    for lay in layouts:
        _store(lay)
        out.append(_card(lay))
    return {"requirements": req.model_dump(), "layouts": out}


def _card(lay: Layout) -> dict[str, Any]:
    return {
        "id": lay.id,
        "score": lay.score,
        "metrics": lay.metrics,
        "notes": lay.notes,
        "estimate": {k: lay.estimate[k] for k in ("total", "per_living_sqft", "within_budget", "budget", "groups")},
        "svg": render_svg(lay, RB, scale=7.5, show_dims=False, compact=True),
    }


@app.get("/api/layouts/{layout_id}")
def api_layout(layout_id: str) -> dict[str, Any]:
    lay = _get(layout_id)
    d = lay.to_dict()
    d["svg"] = render_svg(lay, RB, scale=11)
    return d


@app.get("/api/layouts/{layout_id}/svg")
def api_svg(layout_id: str) -> Response:
    return Response(render_svg(_get(layout_id), RB, scale=11), media_type="image/svg+xml")


@app.get("/api/layouts/{layout_id}/dxf")
def api_dxf(layout_id: str, customer: str = "") -> FileResponse:
    lay = _get(layout_id)
    path = write_dxf(lay, RB, OUTPUT_DIR / "dxf" / f"barndo-{lay.id}.dxf", customer=customer[:80])
    return FileResponse(path, media_type="application/dxf", filename=path.name)


@app.get("/api/layouts/{layout_id}/dwg")
def api_dwg(layout_id: str, customer: str = "") -> FileResponse:
    if not oda_available():
        raise HTTPException(501, "DWG export is not set up on this server (install ODA File Converter).")
    lay = _get(layout_id)
    dxf = write_dxf(lay, RB, OUTPUT_DIR / "dxf" / f"barndo-{lay.id}.dxf", customer=customer[:80])
    try:
        dwg = convert_to_dwg(dxf, OUTPUT_DIR / "dxf")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"DWG conversion failed: {exc}") from exc
    return FileResponse(dwg, media_type="application/acad", filename=dwg.name)


@app.get("/api/layouts/{layout_id}/summary")
def api_summary(layout_id: str, ai: bool = True) -> dict[str, Any]:
    return summarize(_get(layout_id), use_ai=ai)


@app.post("/api/leads")
def api_lead(body: LeadIn) -> dict[str, Any]:
    req: dict[str, Any] = {}
    total = None
    if body.layout_id:
        try:
            lay = _get(body.layout_id)
            req, total = lay.requirements, lay.estimate.get("total")
        except HTTPException:
            pass
    row = leads_mod.save_lead(body.name, str(body.email), body.phone, body.message, body.layout_id, total, req)
    return {"ok": True, "id": row["id"]}


# --- admin -------------------------------------------------------------------
@app.get("/api/admin/leads.csv")
def admin_leads(token: str = "") -> PlainTextResponse:
    _check_admin(token)
    return PlainTextResponse(leads_mod.leads_csv(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


@app.post("/api/admin/reload")
def admin_reload(token: str = "") -> dict[str, Any]:
    _check_admin(token)
    global RB
    RB = load_rulebook()
    create_placeholder_library(RB)
    _cache.clear()
    return {"ok": True, "source": RB.source, "modules": list(RB.modules)}


@app.get("/api/admin/modules")
def admin_modules(token: str = "") -> list[dict[str, Any]]:
    _check_admin(token)
    return validate_library(RB)


@app.get("/api/admin/rulebook.xlsx")
def admin_rulebook(token: str = "") -> FileResponse:
    _check_admin(token)
    return FileResponse(RULEBOOK_PATH, filename="barndo_rules.xlsx")


@app.get("/api/admin/rules")
def admin_rules(token: str = "") -> dict[str, Any]:
    _check_admin(token)
    return RB.summary()


# ---------------------------------------------------------------------------
# Proposal page
# ---------------------------------------------------------------------------
@app.get("/proposal/{layout_id}", response_class=HTMLResponse)
def proposal(layout_id: str, customer: str = "", ai: bool = True) -> str:
    lay = _get(layout_id)
    m, est = lay.metrics, lay.estimate
    summary = summarize(lay, use_ai=ai)["text"]
    svg = render_svg(lay, RB, scale=11)
    rows = "".join(
        f"<tr><td>{escape(s.name)}</td><td>{fmt_ft(cw)} x {fmt_ft(ch)}</td><td class='n'>{round(s.area)}</td></tr>"
        for s in lay.spaces if s.kind in RB.modules for cw, ch in [clear_dims(lay, s, RB.b('ext_wall'), RB.b('int_wall'))])
    groups = "".join(f"<tr><td>{escape(g)}</td><td class='n'>${v:,.0f}</td></tr>" for g, v in est["groups"].items())
    budget_line = ""
    if est.get("budget"):
        ok = est["within_budget"]
        budget_line = (f"<p class='budget {'ok' if ok else 'over'}'>Your budget: ${est['budget']:,.0f} - this plan is "
                       f"{'within' if ok else 'above'} budget.</p>")
    title = f"{COMPANY_NAME} - Concept Plan {lay.id}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<link rel="stylesheet" href="/static/proposal.css"></head><body>
<header><div><h1>{escape(COMPANY_NAME)}</h1><p>Concept floor plan{(' for ' + escape(customer)) if customer else ''} &middot; {date.today():%B %d, %Y}</p></div>
<div class="actions"><button onclick="window.print()">Print / Save PDF</button>
<a href="/api/layouts/{lay.id}/dxf?customer={escape(customer)}">Download DXF</a></div></header>
<main>
<section class="plan">{svg}</section>
<section class="facts">
 <div class="kpis">
  <div><b>{m['footprint']}</b><span>building</span></div>
  <div><b>{m['living_sqft']:,}</b><span>living sq ft</span></div>
  <div><b>{m['shop_sqft']:,}</b><span>shop sq ft</span></div>
  <div><b>{m['bedrooms']} / {m['full_baths']}{('.5' if m['half_baths'] else '')}</b><span>bed / bath</span></div>
  <div><b>${est['total']:,.0f}</b><span>budget estimate</span></div>
 </div>
 <h2>About this plan</h2><p>{escape(summary)}</p>
 {budget_line}
 <div class="cols">
  <div><h2>Rooms</h2><table><tr><th>Room</th><th>Size (clear)</th><th class='n'>Sq ft</th></tr>{rows}</table></div>
  <div><h2>Budget estimate</h2><table>{groups}
   <tr><td>Contingency</td><td class='n'>${est['contingency']:,.0f}</td></tr>
   <tr class='tot'><td>Total</td><td class='n'>${est['total']:,.0f}</td></tr></table>
   <p class="small">{escape(est['disclaimer'])} About ${est['per_living_sqft']:,} per living sq ft.</p></div>
 </div>
 <p class="small">Concept plan generated from {escape(COMPANY_NAME)}'s pre-engineered room modules. Final drawings,
 structural engineering, site work and code review are completed during design development. Plan ID {lay.id}.</p>
</section></main></body></html>"""


# ---------------------------------------------------------------------------
# Static front-end
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}
