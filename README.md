# Barndo Planner

A floor plan generator for barndominiums. Customers describe what they want (in a
form or in plain words), and the app assembles complete concept floor plans from **your
pre-designed room modules**. It applies your construction rules (post spacing, wall
thickness, room size limits, adjacency preferences), prices each option, and outputs:

* an on-screen plan (SVG) with walls, doors, windows, posts, fixtures and dimensions
* a **layered DXF** for AutoCAD / BricsCAD (DWG too, if the ODA converter is installed)
* a printable customer **proposal** page (print to PDF)
* a **budget estimate** from your own unit rates
* a **lead** in your database (and optionally your CRM) when the customer asks for a quote

The AI never draws geometry. Claude only turns the customer's words into a structured
requirements form and writes a friendly description. All geometry comes from a
deterministic engine, so every plan stays inside the rules in your rulebook.

```
 Customer ──► AI intake (Claude) ──► Requirements ──► Layout engine ──► SVG / DXF / proposal / estimate
                (optional)              (form)       rules + modules        │
                                                                            └──► Lead ──► SQLite / CRM webhook
```

---

## Quick start

**Windows:** install Python 3.11+ from python.org, then double-click `start.bat`.
**Mac / Linux:** run `./start.sh`.
Then open <http://localhost:8000>.

Manual install:

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python -m barndo init
```

```bash
python -m barndo serve
```

To turn on the AI features, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.
Without a key, the app still works: it uses a built-in rule-based text parser and
template descriptions.

### Command line

```bash
python -m barndo generate --width 40 --length 80 --beds 4 --baths 2 --shop 30 --mudroom --porch 8 --customer "Smith"
```

This writes `option1_*.svg/.dxf/.json` and the other options to `output/cli/`. Run `python -m barndo --help` for every flag.

---

## How the engine designs a plan

Barndos are rectangles on a structural grid, so the engine fills the rectangle with blocks:

```
 ┌────────┬──────┬────────┬─────────────────┬────────┬──────┬────────┬───────────┐
 │ col A  │      │ col B  │                 │ col B  │      │ col A  │           │
 │bedrooms│ HALL │ baths  │  KITCHEN /      │ baths  │ HALL │bedrooms│   SHOP    │
 │primary │      │laundry │  DINING /       │pantry  │      │mudroom │           │
 │ suite  │      │pantry  │  LIVING         │        │      │        │           │
 └────────┴──────┴────────┴─────────────────┴────────┴──────┴────────┴───────────┘
      left wing                great room          right wing
```

* **Wings** hold two columns of room modules stacked front to back, with a hallway
  between them. Column A (outside) holds rooms that need egress windows. Column B
  (next to the great room) holds baths, laundry and closets, so plumbing groups
  together.
* **No-hall wings:** in small houses, the rooms open straight onto the great room.
* **Rear wing:** for short living areas, all bedrooms run along the back wall and the
  great room spans the front.
* Every room gets a size inside its **min/max** from the rulebook, aiming for the
  **preferred** size. Leftover space becomes a storage closet.
* Doors, windows and exterior openings are placed between **posts** at your bay
  spacing. Bedrooms must get an egress window on an outside wall, or the option is
  rejected.
* The engine tries hundreds of arrangements (which wing gets the primary suite, room
  order, column depths), rejects any that break a rule, scores the rest, and returns
  the best distinct options. The score covers room sizes, great room proportions,
  hallway waste, plumbing grouping, split plan, the adjacency rules in your rulebook,
  corner bedrooms and daylight.
* Every candidate is checked against the **Company Rules** (below); anything that breaks a
  hard rule is rejected. The options returned come from different design concepts
  (split plan, single wing, rear wing, open flow or short hallway, kitchen position), and
  each gets a short concept name.
* If nothing fits, the engine steps down the "nice to haves" (walk-in closet → reach-in,
  then pantry, mudroom, office) and says what it changed. If the building is too big for
  the room list, it adds flex rooms. If it still can't fit, the customer gets a plain
  explanation instead of a bad plan.

The same input always produces the same plans, so you can reproduce a plan from its ID.

---

## Making it yours

### 1. The rulebook: `rules/barndo_rules.xlsx`

| Sheet | What it controls |
|---|---|
| **Modules** | One row per room type: min / max / preferred width & depth, wet room, needs exterior wall, windows, door width, finish $/sqft, fixture cost, DXF drawing, colour |
| **Adjacency** | `prefer` / `avoid` pairs with weights (e.g. mudroom next to shop, bedroom away from shop) |
| **Building** | Post spacing, wall thicknesses, hall width, overhead door width, candidate column depths, minimum shop length |
| **Pricing** | Unit rates for the estimate. **The shipped values are placeholders. Replace them with your real costs.** |
| **Company Rules** | Your design rules; every plan is checked against them (see below) |
| **Footprints** | Building sizes shown in the configurator |

Room dimension convention: **w** is measured along the wall with the room's entry door,
and **d** is the depth into the room. All values are in feet.

After editing, restart the app or call `POST /api/admin/reload?token=...`.

### 2. Company rules (checked on every plan)

The **Company Rules** sheet holds your design rules. Every plan is checked against them
before anyone sees it. A plan that breaks a **hard** rule is thrown away; a **soft** rule
only adds a warning. Each plan shows a ✓ checklist in the app and on the proposal.

| # | Rule | Check type |
|---|---|---|
| 1 | Each full bath has at least a sink, toilet and shower | `required_fixtures` (reads the fixture blocks in the bath DXF) |
| 2 | No hallway when the doors can open to an open space | `no_unneeded_hallway` |
| 3 | Doors at the side of the wall, not in the middle | `doors_near_corner` |
| 4 | Standard 3x4 windows; doubles in primary bedroom, living, kitchen | `window_standard` |
| 5 | Doors 6'-8" high; main entrance single 3' or double 6' | `door_standard` |
| 6 | Laundry + mudroom are one room; bedrooms, kitchen, office, living have windows | `laundry_mud_and_windows` |
| 7 | Bedrooms at least 12' x 12' clear | `min_clear_size` |
| 8 | Bathrooms at least 5'-4" wide clear | `min_clear_width` |
| 9 | Keep walkways to a minimum (soft, target ≤ 12% of living area) | `max_circulation_pct` |
| 10 | Cost estimates include eave height and slope | `estimate_uses_eave_and_slope` |
| 11 | Standard 12' eave and 4:12 slope (soft: flags customer changes) | `building_standard` |
| 12 | Exterior walls 6", interior 4" | `wall_thickness` |
| 13 | Every door swings clear of fixtures, furniture and other doors | `door_swing_clear` |

**Adding a rule:** add a row. Most new rules reuse an existing check type, so they need no
code. Examples:

| id | rule | check | applies_to | value | severity | enabled |
|---|---|---|---|---|---|---|
| 13 | Office at least 10x10 | `min_clear_size` | office | 10x10 | hard | Y |
| 14 | Flex room must have a window | `must_have_window` | flex | | hard | Y |
| 15 | Laundry never next to a bedroom | `not_adjacent` | laundry_mud,bedroom | | soft | Y |
| 16 | Pantry must open off the kitchen | `must_be_adjacent` | pantry,great_room | | hard | Y |

Available check types: `required_fixtures`, `no_unneeded_hallway`, `doors_near_corner`,
`window_standard`, `door_standard`, `laundry_mud_and_windows`, `must_have_window`,
`min_clear_size`, `min_clear_width`, `max_circulation_pct`, `not_adjacent`,
`must_be_adjacent`, `estimate_uses_eave_and_slope`, `building_standard`, `wall_thickness`,
`door_swing_clear`.
`kitchen` and `living` can be used in `applies_to` for the two halves of the great room.
A rule that needs new logic is a small function in `barndo/design_rules.py`.

The building standards behind the rules (wall thicknesses, door height, entry widths,
window size, eave height, roof slope, overhang) are in the **Building** sheet. Eave height
and roof slope can also be changed per customer in the app; the estimate prices exterior
walls (perimeter × eave + gables) and the sloped roof area from them.

### 3. The module drawings: `modules/*.dxf` (your puzzle pieces)

The repo ships placeholder fixture drawings (beds, tubs, kitchen run...) so it works out
of the box. Replace them with your own drawings, following this standard:

* Units: **inches**
* Draw **only fixtures / cabinets / furniture**. No walls, doors or windows; the engine draws those.
* Origin (0,0) is the bottom-left corner of the module's **minimum** size box (min_w × min_d).
* The **door wall is the bottom edge** (y = 0). Beds, tubs and counters go against the
  back wall (y = min_d).
* Keep everything inside the min box. Use the layers `FIXTURE` and `FURNITURE`.
* Draw fixtures as **named blocks**. Rule 1 reads them: a full bath needs blocks named
  like `SINK` (or `LAV`/`VANITY`), `TOILET` (or `WC`) and `SHOWER`.

Check your library with:

```bash
python -m barndo validate-modules
```

In the output DXF, every module is inserted as a named block (`MOD_MASTER_BATH`...), so
your CAD team can edit or swap them.

### 4. Adding a new room type

Add a row to **Modules** (e.g. `safe_room`), draw `modules/safe_room.dxf`, and wire it
into `room_program()` / `random_plan()` in `barndo/solver.py` and the form in
`web/index.html`.

---

## DXF layers

`A-WALL` / `A-WALL-PATT` walls · `A-DOOR` doors & swings · `A-GLAZ` windows · `A-OVHD` overhead doors ·
`S-COLS` posts · `A-AREA` room boundaries · `A-AREA-IDEN` room names, sizes, areas · `A-FURN` module blocks ·
`A-DIMS` dimensions · `A-PORCH` porches · `A-ANNO-TTLB` title block + room schedule.

**DWG:** install the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
and set `ODA_FILE_CONVERTER` to its path. A "Download DWG" button then appears.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Company, footprints, whether AI / DWG are on |
| POST | `/api/intake` | `{text}` → requirements + assumptions + follow-up questions |
| POST | `/api/layouts` | Requirements JSON → up to 6 scored options with SVG thumbnails |
| GET | `/api/layouts/{id}` | Full layout data + large SVG |
| GET | `/api/layouts/{id}/dxf` · `/dwg` · `/svg` | Downloads |
| GET | `/api/layouts/{id}/summary` | Customer-facing description |
| GET | `/proposal/{id}` | Printable proposal page |
| POST | `/api/leads` | Save a quote request (also POSTs to `BARNDO_LEAD_WEBHOOK_URL`) |
| GET | `/api/admin/leads.csv?token=` | Export leads |
| POST | `/api/admin/reload?token=` | Reload rulebook + modules |
| GET | `/api/admin/modules?token=` | Validate module library |
| GET | `/api/admin/rules?token=` · `/rulebook.xlsx?token=` | View / download rulebook |

Interactive docs: <http://localhost:8000/docs>.

### Connecting a chatbot (Voiceflow, Botpress, Tray...)

You don't need one, because the web app has the conversational box built in. If you
already use a chat platform, have it call `POST /api/intake` with the conversation text,
then `POST /api/layouts` with the returned requirements. Show the `/proposal/{id}` link to
the customer.

---

## Deploying

```bash
docker compose up -d --build
```

The rulebook, modules, leads and outputs are mounted from the host, so your team can
edit the Excel file and drawings without rebuilding. Put it behind HTTPS (Caddy, Nginx,
Cloudflare Tunnel, or a host like Render / Railway / Fly.io) and set `BARNDO_ADMIN_TOKEN`.

## Tests

```bash
python -m pytest -q
```

The tests check, across many building sizes and room programs, that rooms tile the
footprint with no overlaps, every room stays inside its module limits, bedrooms get
egress windows, every room has a door, the primary bath opens off the primary bedroom,
openings avoid posts, the shop has access, outputs are valid DXF, and the API works end to end.

---

## Limits (what to tell customers and staff)

* These are **concept plans**. Structural engineering, code review (egress sizes,
  energy, fire separation between shop and living space), site work and final CDs still
  go through your normal process.
* Single-story, rectangular footprints. Lofts, L-shapes and wraparound porches need
  manual design development.
* Costs are only as good as the rates in the **Pricing** sheet.

## Project layout

```
barndo/
  rules.py           rulebook (Excel) loading + defaults
  requirements.py    customer requirements model
  solver.py          layout engine (search, sizing, doors, windows, scoring)
  layout.py, walls.py  geometry model
  module_library.py  module DXF standard, placeholders, validation, placement
  render_svg.py      on-screen plans
  render_dxf.py      CAD output + DWG conversion
  estimate.py        cost estimate
  intake.py          AI / rule-based intake
  summary.py         customer description
  leads.py           lead storage + webhook
  api.py             FastAPI app + proposal page
web/                 front-end (plain HTML/CSS/JS)
rules/               barndo_rules.xlsx
modules/             room module DXFs
tests/               pytest suite
```
