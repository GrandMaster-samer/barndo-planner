"""Command line: python -m barndo <command>

  serve               run the web app (http://localhost:8000)
  generate            generate layouts and write SVG + DXF files
  init                create the Excel rulebook and placeholder module drawings
  validate-modules    check the module DXF library against the drawing standard
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import OUTPUT_DIR


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="barndo", description="Barndominium layout engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    g = sub.add_parser("generate", help="generate layouts")
    g.add_argument("--width", type=float, default=40)
    g.add_argument("--length", type=float, default=60)
    g.add_argument("--beds", type=int, default=3)
    g.add_argument("--baths", type=int, default=2)
    g.add_argument("--half-baths", type=int, default=0)
    g.add_argument("--shop", type=float, default=0, help="shop length in feet")
    g.add_argument("--shop-side", choices=["left", "right"], default="right")
    g.add_argument("--porch", type=float, default=0, help="front porch depth")
    g.add_argument("--back-porch", type=float, default=0)
    for flag in ("office", "pantry", "mudroom"):
        g.add_argument(f"--{flag}", action="store_true")
    g.add_argument("--no-wic", action="store_true")
    g.add_argument("--count", type=int, default=6)
    g.add_argument("--json", help="read requirements from a JSON file instead of flags")
    g.add_argument("--out", default=str(OUTPUT_DIR / "cli"))
    g.add_argument("--customer", default="")

    i = sub.add_parser("init", help="create rulebook and placeholder modules")
    i.add_argument("--force", action="store_true", help="overwrite existing files")

    sub.add_parser("validate-modules", help="check module DXFs")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("barndo.api:app", host=a.host, port=a.port)
        return 0

    from .module_library import create_placeholder_library, validate_library
    from .rules import load_rulebook, write_default_rulebook

    if a.cmd == "init":
        p = write_default_rulebook(overwrite=a.force)
        made = create_placeholder_library(load_rulebook(), overwrite=a.force)
        print(f"Rulebook: {p}")
        print(f"Module drawings written: {len(made)}")
        return 0

    if a.cmd == "validate-modules":
        bad = 0
        for r in validate_library(load_rulebook()):
            print(f"{r['status']:<10} {r['module']:<16} {r['file']}")
            for issue in r["issues"]:
                print(f"           - {issue}")
            bad += r["status"] in ("missing", "error")
        return 1 if bad else 0

    from .render_dxf import write_dxf
    from .render_svg import render_svg
    from .requirements import Requirements
    from .solver import LayoutError, generate_layouts

    if a.json:
        req = Requirements(**json.loads(Path(a.json).read_text()))
    else:
        req = Requirements(building_width=a.width, building_length=a.length, bedrooms=a.beds, full_baths=a.baths,
                           half_baths=a.half_baths, shop_length=a.shop, shop_side=a.shop_side,
                           front_porch_depth=a.porch, back_porch_depth=a.back_porch, office=a.office,
                           pantry=a.pantry, mudroom=a.mudroom, walk_in_closet=not a.no_wic)
    rb = load_rulebook()
    try:
        layouts = generate_layouts(req, rb, count=a.count)
    except LayoutError as exc:
        print(f"No layout: {exc}", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for n, lay in enumerate(layouts, start=1):
        (out / f"option{n}_{lay.id}.svg").write_text(render_svg(lay, rb))
        write_dxf(lay, rb, out / f"option{n}_{lay.id}.dxf", customer=a.customer)
        (out / f"option{n}_{lay.id}.json").write_text(json.dumps(lay.to_dict(), indent=1))
        print(f"Option {n}: score {lay.score:5.1f}  est ${lay.estimate['total']:,.0f}  {lay.metrics['living_sqft']} sf living"
              f"  great room {lay.metrics['great_room']}  {' '.join(lay.notes)}")
    print(f"Files written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
