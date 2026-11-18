import ezdxf

from barndo.module_library import validate_library
from barndo.render_dxf import write_dxf
from barndo.render_svg import render_svg
from barndo.requirements import Requirements
from barndo.rules import load_rulebook, write_default_rulebook
from barndo.solver import generate_layouts
from barndo.layout import layout_from_dict

RB = load_rulebook()


def _layout():
    return generate_layouts(Requirements(shop_length=30, building_length=80, pantry=True, front_porch_depth=8), RB, count=1)[0]


def test_svg_renders():
    svg = render_svg(_layout(), RB)
    assert svg.startswith("<svg") and "KITCHEN / DINING / LIVING" in svg and "SHOP" in svg


def test_dxf_is_valid(tmp_path):
    lay = _layout()
    p = write_dxf(lay, RB, tmp_path / "plan.dxf", customer="Test")
    doc = ezdxf.readfile(p)
    auditor = doc.audit()
    assert not auditor.has_errors
    layers = {e.dxf.layer for e in doc.modelspace()}
    for needed in ("A-WALL", "A-DOOR", "A-GLAZ", "S-COLS", "A-AREA-IDEN", "A-DIMS"):
        assert needed in layers
    assert any(e.dxftype() == "INSERT" and e.dxf.name.startswith("MOD_") for e in doc.modelspace())
    assert doc.header["$INSUNITS"] == 1


def test_layout_roundtrip():
    lay = _layout()
    again = layout_from_dict(lay.to_dict())
    assert again.id == lay.id and len(again.spaces) == len(lay.spaces) and len(again.doors) == len(lay.doors)
    assert render_svg(again, RB) == render_svg(lay, RB)


def test_module_library_valid():
    for r in validate_library(RB):
        assert r["status"] in ("ok", "no drawing"), r


def test_rulebook_roundtrip(tmp_path):
    p = write_default_rulebook(tmp_path / "rules.xlsx", overwrite=True)
    import openpyxl
    wb = openpyxl.load_workbook(p)
    ws = wb["Modules"]
    header = [c.value for c in ws[1]]
    row = next(r for r in ws.iter_rows(min_row=2) if r[0].value == "bedroom")
    row[header.index("min_w")].value = 11
    wb["Pricing"].append(["custom_rate", 5, "test"])
    wb.save(p)
    from barndo.rules import load_rulebook as lr
    rb = lr(p)
    assert rb.m("bedroom").min_w == 11
    assert rb.pricing["custom_rate"] == 5
    assert rb.b("hall_width") == 4
