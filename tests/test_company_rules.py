"""Every plan the engine returns must satisfy the company rules."""
import dataclasses

import pytest

from barndo.design_rules import CHECKS, check_layout
from barndo.layout import clear_dims
from barndo.requirements import Requirements
from barndo.rules import CompanyRule, load_rulebook
from barndo.solver import generate_layouts

RB = load_rulebook()

CASES = [
    dict(),
    dict(shop_length=20, pantry=True),
    dict(building_length=80, shop_length=30, bedrooms=3, half_baths=1, mudroom=True, office=True, main_entrance="double"),
    dict(building_width=50, building_length=80, bedrooms=4, full_baths=3, shop_length=30, shop_side="left"),
    dict(building_width=30, building_length=50, bedrooms=2, full_baths=1, front_porch_depth=10),
]


@pytest.fixture(scope="module", params=range(len(CASES)))
def layouts(request):
    req = Requirements(**CASES[request.param])
    return req, generate_layouts(req, RB, count=6)


def test_all_twelve_rules_are_loaded():
    assert [r.id for r in RB.rules][:13] == [str(i) for i in range(1, 14)]
    assert all(r.check in CHECKS for r in RB.rules)


def test_no_plan_breaks_a_hard_rule(layouts):
    _, ls = layouts
    for lay in ls:
        assert len(lay.rule_checks) == len(RB.rules)
        bad = [r for r in lay.rule_checks if r["status"] in ("fail", "unknown")]
        assert not bad, bad


def test_rule7_bedrooms_12x12_clear(layouts):
    _, ls = layouts
    for lay in ls:
        for s in lay.spaces:
            if s.kind in ("bedroom", "master_bedroom"):
                assert min(clear_dims(lay, s, RB.b("ext_wall"), RB.b("int_wall"))) >= 12 - 0.01, s.name


def test_rule8_baths_5ft4_clear(layouts):
    _, ls = layouts
    for lay in ls:
        for s in lay.spaces:
            if s.kind in ("full_bath", "master_bath", "half_bath"):
                assert min(clear_dims(lay, s, RB.b("ext_wall"), RB.b("int_wall"))) >= 5.333 - 0.01, s.name


def test_rule6_laundry_and_mudroom_are_one_room(layouts):
    req, ls = layouts
    for lay in ls:
        kinds = [s.kind for s in lay.spaces]
        assert "laundry" not in kinds and "mudroom" not in kinds
        assert kinds.count("laundry_mud") == int(req.laundry or req.mudroom)


def test_rule4_rule5_openings(layouts):
    req, ls = layouts
    for lay in ls:
        for w in lay.windows:
            assert w.height == 4 and w.width == 3 * w.units
        for d in lay.doors:
            if d.kind in ("interior", "exterior"):
                assert d.height == pytest.approx(6.667, abs=0.01)
        main = [d for d in lay.doors if d.kind == "exterior" and d.serves == "great_room" and d.y == 0]
        assert len(main) == 1
        assert main[0].width == (6 if req.main_entrance == "double" else 3)
        assert main[0].leaves == (2 if req.main_entrance == "double" else 1)


def test_rule10_estimate_uses_eave_and_slope():
    req = Requirements()
    base = generate_layouts(req, RB, count=1)[0]
    steep = generate_layouts(req.model_copy(update={"roof_pitch": 8, "eave_height": 16}), RB, count=1)[0]
    b1, b2 = base.estimate["building"], steep.estimate["building"]
    assert (b1["eave_height"], b1["roof_pitch"]) == (12, 4)
    assert b2["roof_area_sqft"] > b1["roof_area_sqft"] and b2["wall_area_sqft"] > b1["wall_area_sqft"]
    assert steep.estimate["groups"]["Shell"] > base.estimate["groups"]["Shell"]
    # rule 11 is a soft rule: non-standard eave/slope is flagged, not rejected
    r11 = next(r for r in steep.rule_checks if r["id"] == "11")
    assert r11["status"] == "warn"


def test_rule1_detects_missing_shower():
    lay = generate_layouts(Requirements(), RB, count=1)[0]
    rb = load_rulebook()
    rb.modules["full_bath"] = dataclasses.replace(rb.m("full_bath"), dxf_file="half_bath.dxf")  # sink + toilet only
    r1 = next(r for r in check_layout(lay, rb) if r["id"] == "1")
    assert r1["status"] == "fail" and "shower" in r1["detail"]


def test_new_rule_rows_work_without_code():
    lay = generate_layouts(Requirements(office=True), RB, count=1)[0]
    rb = load_rulebook()
    rb.rules.append(CompanyRule("13", "Office at least 20x20", "min_clear_size", ["office"], "20x20", "hard"))
    rb.rules.append(CompanyRule("14", "Typo check", "no_such_check", [], "", "hard"))
    res = {r["id"]: r for r in check_layout(lay, rb)}
    assert res["13"]["status"] == "fail"
    assert res["14"]["status"] == "unknown"


def test_plans_are_varied(layouts):
    _, ls = layouts
    if len(ls) >= 3:
        assert len({l.signature.split(" k")[0] for l in ls}) == len(ls)
        assert all(l.concept for l in ls)


def test_rule13_doors_swing_clear(layouts):
    from barndo.clearance import door_conflict, fixture_geometry
    _, ls = layouts
    for lay in ls:
        fx = fixture_geometry(lay, RB)
        for d in lay.doors:
            assert door_conflict(d, lay, RB, fx, lay.doors) == "", (d.serves, d.x, d.y)


def test_rule13_detects_a_blocked_door():
    from barndo.clearance import door_conflict, fixture_geometry
    from barndo.layout import Door
    lay = generate_layouts(Requirements(), RB, count=1)[0]
    bath = next(s for s in lay.spaces if s.kind == "master_bath")
    fx = fixture_geometry(lay, RB)
    # a door swinging into the middle of the bath from every wall must hit something somewhere
    hits = 0
    for x in [bath.x0 + k * 0.5 for k in range(2, int(bath.w * 2) - 2)]:
        for y, into in ((bath.y0, 1), (bath.y1, -1)):
            d = Door(x, y, "x", 3, "interior", into=into, serves=bath.id)
            hits += bool(door_conflict(d, lay, RB, fx, []))
    assert hits > 0
