from fastapi.testclient import TestClient

from barndo.intake import extract_with_rules, intake


def test_rules_parser_basic():
    e = extract_with_rules("40x60 barndo with a 20 ft shop, 3 bedroom 2.5 bath, office and pantry, front porch, $350k")
    assert (e.building_width, e.building_length) == (40, 60)
    assert e.bedrooms == 3 and e.full_baths == 2 and e.half_baths == 1
    assert e.shop_length == 20 and e.office and e.pantry
    assert e.front_porch_depth == 10 and e.budget == 350_000


def test_rules_parser_shop_dims_and_sqft():
    e = extract_with_rules("50 by 100 with a 30x50 shop and 4 beds 3 baths")
    assert e.building_width == 50 and e.shop_length == 30 and e.bedrooms == 4
    e = extract_with_rules("about 2000 sq ft, two bedrooms")
    assert e.building_width == 40 and e.building_length == 50 and e.bedrooms == 2


def test_intake_asks_questions():
    out = intake("I want a barndo")
    assert out["engine"] == "rules"
    assert out["questions"]


def test_api_flow():
    from barndo.api import app
    c = TestClient(app)
    cfg = c.get("/api/config").json()
    assert cfg["footprints"] and cfg["defaults"]["bedrooms"] == 3
    r = c.post("/api/intake", json={"text": "40x70, 30 ft shop, 3 bed 2 bath, mudroom"}).json()
    req = r["requirements"]
    assert req["shop_length"] == 30
    res = c.post("/api/layouts", json=req)
    assert res.status_code == 200, res.text
    lay = res.json()["layouts"][0]
    assert lay["svg"].startswith("<svg")
    lid = lay["id"]
    assert c.get(f"/api/layouts/{lid}").json()["metrics"]["shop_sqft"] == 1200
    dxf = c.get(f"/api/layouts/{lid}/dxf")
    assert dxf.status_code == 200 and b"SECTION" in dxf.content[:200]
    assert "About this plan" in c.get(f"/proposal/{lid}?ai=false").text
    assert c.get(f"/api/layouts/{lid}/summary?ai=false").json()["engine"] == "template"
    assert c.post("/api/leads", json={"name": "A", "email": "a@b.co", "layout_id": lid}).json()["ok"]
    assert c.post("/api/leads", json={"name": "A", "email": "nope"}).status_code == 422
    assert c.get("/api/admin/leads.csv").status_code == 403
    csv = c.get("/api/admin/leads.csv?token=test-token")
    assert csv.status_code == 200 and "a@b.co" in csv.text
    assert c.get("/api/layouts/nope-1").status_code == 404
    bad = c.post("/api/layouts", json={"building_width": 30, "building_length": 40, "bedrooms": 6, "full_baths": 4})
    assert bad.status_code == 422
