"""CR's Form ND2B as the client and CR receive it (spec §7), with its
typography measured as ND2A's is."""
import functools
import io

import pytest
from pypdf import PdfReader

from services.nar1_form import appearance as ap
from services.officer_change_form import nd2b_map as m
from services.officer_change_form import page_plan, render, render_fields
from services.officer_changes import form_xml, nd2b_mapper
from tests.officer_changes import cr_fixtures as fx
from tests.officer_changes.test_nd2a_geometry import runs

COMPANY = "KANENAS HOLDING LIMITED"
OVERFLOW = ["Change Individual Director", "Change Individual Secretary",
            "Change Corporate Director", "Change Corporate Secretary"]


def _xml(path=None, *, world=None, mutate=None):
    graph, entries = world or fx.build_world(path)
    if mutate:
        mutate(graph, entries)
    return form_xml.build("Nd2b", nd2b_mapper.map_case(graph, entries))


@functools.lru_cache(maxsize=1)
def overflow_xml():
    return _xml(world=fx.combined_world("ND2B", OVERFLOW,
                                        {1: {"surname": "WONG", "given_names": "KA YAN"}}))


def _text(pdf):
    return [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]


def _values(xml, page_index, **kw):
    filled = PdfReader(io.BytesIO(render_fields("Nd2b", xml, company_name=COMPANY, **kw)))
    return {str(a.get_object().get("/T")).split("__p")[0]: str(a.get_object().get("/V") or "")
            for a in filled.pages[page_index].get("/Annots") or []}


@pytest.mark.parametrize("path", fx.files("ND2B"), ids=lambda p: p.name)
def test_every_example_renders_flat(path):
    xml = _xml(path)
    pdf = render("Nd2b", xml, company_name=COMPANY)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == len(page_plan("Nd2b", xml))
    assert "/AcroForm" not in reader.trailer["/Root"]
    text = "\n".join(_text(pdf))
    assert "00000001" in text and COMPANY in text and "None" not in text


def test_overflow_generates_both_sheets_and_a_pi_per_changed_identity():
    plan = [p["sheet"] for p in page_plan("Nd2b", overflow_xml())]
    assert plan == ["1", "2", "3", "A", "B", "PI", "PI"]
    counts = _values(overflow_xml(), 2)
    assert (counts[m.MAIN_3["count_sheet_a"]], counts[m.MAIN_3["count_sheet_b"]],
            counts[m.MAIN_3["count_pi"]]) == ("1", "1", "2")
    public = [p["sheet"] for p in page_plan("Nd2b", overflow_xml(), public_only=True)]
    assert public == ["1", "2", "3", "A", "B"]


def test_an_email_only_change_has_no_pi_sheet():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)

    def email_only(graph, entries):
        entries[0]["items"] = [i for i in entries[0]["items"] if i["key"] == "email"]

    assert [p["sheet"] for p in page_plan("Nd2b", _xml(path, mutate=email_only))] == \
        ["1", "2", "3"]


def test_unchanged_items_stay_empty_and_each_change_carries_its_date():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)

    def email_only(graph, entries):
        entries[0]["items"] = [i for i in entries[0]["items"] if i["key"] == "email"]

    values = _values(_xml(path, mutate=email_only), 1)
    assert values[m.MAIN_2["new_email"]] == "test@cr.gov.hk"
    assert (values[m.MAIN_2["email_date_dd"]], values[m.MAIN_2["email_date_mm"]],
            values[m.MAIN_2["email_date_yyyy"]]) == ("06", "06", "2022")
    assert values[m.MAIN_2["new_name_zh"]] == "" and values[m.MAIN_2["corr_flat"]] == ""


def test_the_new_hkid_is_partial_in_public_and_full_on_the_pi_sheet():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)
    pages = _text(render("Nd2b", _xml(path), company_name=COMPANY))
    assert "A123" in pages[1] and "A123456" not in pages[1]
    assert "A123456" in pages[3] and "H12345678" in pages[3]


def test_part_a_prints_the_registered_name():
    path = next(p for p in fx.files("ND2B") if "Individual Director" in p.name)

    def renamed(graph, entries):
        entries[0]["registered"]["name_en"] = {"surname": "OLDNAME", "given_names": "X"}

    assert "OLDNAME" in _text(render("Nd2b", _xml(path, mutate=renamed),
                                     company_name=COMPANY))[0]


# -- typography ----------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def rendered():
    return PdfReader(io.BytesIO(render("Nd2b", overflow_xml(), company_name=COMPANY,
                                       submitted_on="2026-10-02")))


@functools.lru_cache(maxsize=1)
def filled():
    return PdfReader(io.BytesIO(render_fields("Nd2b", overflow_xml(), company_name=COMPANY,
                                              submitted_on="2026-10-02")))


def _box(field, index):
    for annot in filled().pages[index].get("/Annots") or []:
        obj = annot.get_object()
        if str(obj.get("/T")).split("__p")[0] == field:
            r = [float(v) for v in obj["/Rect"]]
            return min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])
    raise AssertionError(field)


def _drawn(field, index):
    x0, y0, x1, y1 = _box(field, index)
    hit = [r for r in runs(rendered().pages[index])
           if x0 - 1 <= r[1] <= x1 and y0 - 2 <= r[2] <= y1 + 2]
    assert hit, field
    return sorted(hit, key=lambda r: -r[2])[0]


@pytest.mark.parametrize("field, index, size, bold", [
    (m.MAIN_1["br_number"], 0, 14.0, True), (m.MAIN_1["company_name"], 0, 12.0, True),
    (m.MAIN_1["surname_en"], 0, 10.0, True), (m.MAIN_1["presenter_name"], 0, 10.0, False),
    (m.MAIN_2["new_email"], 1, 10.0, True), (m.MAIN_3["name_en"], 2, 10.0, True),
    (m.SHEET_A["new_surname_en"], 3, 10.0, True), (m.PI["hkid_full"], 5, 10.0, True),
])
def test_sizes_and_weights_are_nar1s(field, index, size, bold):
    _t, _x, _y, got, face = _drawn(field, index)
    assert got == pytest.approx(size, abs=0.05)
    assert ("Bold" in face) is bold


@pytest.mark.parametrize("field, index", [
    (m.MAIN_1["surname_en"], 0), (m.MAIN_2["new_email"], 1), (m.SHEET_A["corr_street"], 3)])
def test_left_values_start_9_4pt_inside(field, index):
    _t, x, _y, _s, _f = _drawn(field, index)
    assert x == pytest.approx(_box(field, index)[0] + 9.4, abs=0.3)


@pytest.mark.parametrize("field, index", [
    (m.MAIN_2["email_date_dd"], 1), (m.MAIN_2["new_hkid_partial"], 1),
    (m.MAIN_3["own_br_number"], 2), (m.MAIN_3["signed_date"], 2)])
def test_centred_cells(field, index):
    text, x, _y, size, _f = _drawn(field, index)
    x0, _y0, x1, _y1 = _box(field, index)
    assert x == pytest.approx(x0 + ((x1 - x0) - ap.measure(text, size)) / 2, abs=0.6)
