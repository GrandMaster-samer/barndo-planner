import itertools

import pytest

from barndo.layout import EPS, shared_edge
from barndo.requirements import Requirements
from barndo.rules import load_rulebook
from barndo.solver import LayoutError, generate_layouts

RB = load_rulebook()

CASES = [
    dict(),
    dict(shop_length=20),
    dict(shop_length=30, building_length=80, bedrooms=4, half_baths=1, pantry=True, mudroom=True, office=True),
    dict(building_width=30, building_length=50, bedrooms=2, full_baths=1),
    dict(building_width=50, building_length=80, bedrooms=4, full_baths=3, shop_length=30, shop_side="left"),
    dict(building_width=40, building_length=70, bedrooms=3, full_baths=2, front_porch_depth=10, back_porch_depth=8),
    dict(building_width=40, building_length=100, bedrooms=5, full_baths=3, shop_length=40, overhead_doors=2),
]


@pytest.fixture(scope="module", params=range(len(CASES)))
def layouts(request):
    req = Requirements(**CASES[request.param])
    return req, generate_layouts(req, RB, count=4)


def test_returns_options(layouts):
    _, ls = layouts
    assert 1 <= len(ls) <= 4
    assert [l.score for l in ls] == sorted([l.score for l in ls], reverse=True)
    assert len({l.id for l in ls}) == len(ls)


def test_spaces_tile_the_footprint(layouts):
    _, ls = layouts
    for lay in ls:
        total = sum(s.area for s in lay.spaces)
        assert total == pytest.approx(lay.length * lay.width, abs=0.5)
        for a, b in itertools.combinations(lay.spaces, 2):
            ox = min(a.x1, b.x1) - max(a.x0, b.x0)
            oy = min(a.y1, b.y1) - max(a.y0, b.y0)
            assert not (ox > EPS and oy > EPS), f"{a.id} overlaps {b.id}"
            assert -EPS <= a.x0 and a.x1 <= lay.length + EPS and -EPS <= a.y0 and a.y1 <= lay.width + EPS


def test_rooms_respect_module_limits(layouts):
    _, ls = layouts
    for lay in ls:
        for s in lay.spaces:
            if s.kind not in RB.modules or s.kind == "great_room":
                continue
            m = RB.m(s.kind)
            w, d = s.local_wd()
            assert m.min_w - 0.3 <= w <= m.max_w + 0.3, (s.id, w)
            assert m.min_d - 0.3 <= d <= m.max_d + 0.3, (s.id, d)


def test_program_is_delivered(layouts):
    req, ls = layouts
    for lay in ls:
        kinds = [s.kind for s in lay.spaces]
        assert kinds.count("master_bedroom") == 1
        assert kinds.count("master_bath") == 1
        assert kinds.count("bedroom") == req.bedrooms - 1
        assert kinds.count("full_bath") == req.full_baths - 1
        assert kinds.count("half_bath") == req.half_baths
        assert ("shop" in kinds) == (req.shop_length > 0)


def test_bedrooms_have_egress_windows(layouts):
    _, ls = layouts
    for lay in ls:
        for s in lay.spaces:
            if s.kind in RB.modules and RB.m(s.kind).needs_exterior:
                assert lay.exterior_sides(s), s.id
                assert any(w.serves == s.id for w in lay.windows), f"{s.id} has no window"


def test_every_room_has_a_door(layouts):
    _, ls = layouts
    for lay in ls:
        served = {d.serves for d in lay.doors}
        for s in lay.spaces:
            if s.kind in RB.modules and s.kind != "great_room":
                assert s.id in served, f"{s.id} has no door"


def test_primary_suite_connects(layouts):
    _, ls = layouts
    for lay in ls:
        bed = next(s for s in lay.spaces if s.kind == "master_bedroom")
        bath = next(s for s in lay.spaces if s.kind == "master_bath")
        assert shared_edge(bed, bath), "primary bath must open off the primary bedroom"


def test_openings_avoid_posts(layouts):
    _, ls = layouts
    half = RB.b("post_size") / 2
    for lay in ls:
        openings = [(d.x, d.y, d.axis, d.width) for d in lay.doors if d.wall == "ext" and d.kind != "overhead"]
        openings += [(w.x, w.y, w.axis, w.width) for w in lay.windows]
        for x, y, axis, width in openings:
            for px, py in lay.posts:
                if axis == "x" and abs(py - y) < EPS:
                    assert abs(px - x) >= width / 2 + half - 1e-3, (x, y, px)
                if axis == "y" and abs(px - x) < EPS:
                    assert abs(py - y) >= width / 2 + half - 1e-3, (x, y, py)


def test_shop_has_access(layouts):
    req, ls = layouts
    if not req.shop_length:
        return
    for lay in ls:
        assert any(d.wall == "shop" for d in lay.doors)
        if req.overhead_doors:
            assert any(d.kind == "overhead" for d in lay.doors)


def test_shop_side_left(layouts):
    req, ls = layouts
    if req.shop_side != "left" or not req.shop_length:
        return
    for lay in ls:
        shop = lay.space("shop")
        assert shop.x0 == pytest.approx(0)


def test_deterministic():
    req = Requirements(shop_length=20, pantry=True)
    a = generate_layouts(req, RB, count=3)
    b = generate_layouts(req, RB, count=3)
    assert [l.signature for l in a] == [l.signature for l in b]


def test_impossible_program_explains_itself():
    with pytest.raises(LayoutError) as exc:
        generate_layouts(Requirements(building_width=30, building_length=40, bedrooms=6, full_baths=4), RB)
    assert "No valid layout" in str(exc.value)


def test_shop_too_short_rejected():
    with pytest.raises(LayoutError):
        generate_layouts(Requirements(shop_length=6), RB)


def test_estimate_adds_up(layouts):
    _, ls = layouts
    for lay in ls:
        e = lay.estimate
        assert e["subtotal"] == sum(l["amount"] for l in e["lines"])
        assert e["total"] == e["subtotal"] + e["contingency"]
        assert e["total"] > 100_000
