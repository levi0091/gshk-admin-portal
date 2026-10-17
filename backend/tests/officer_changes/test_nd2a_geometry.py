"""ND2A's typography, MEASURED off the rendered pages (answer 15: "font size
standardised with the ones we used in NAR1").

NAR1's sizes were measured off a filed return (`test_nar1_specimen_geometry`):
every value Times-metric Bold 10pt, the header BR number 14pt, the company name
12pt, the presenter's block regular, a left value 9.4pt inside its box, a
single line's baseline at y0 + (h - 0.72 x size) / 2. The same renderer core
draws ND2A, and this file proves it did so on ND2A's own boxes.
"""
import functools
import io

import pytest

pytest.importorskip("pymupdf")
from pypdf import PdfReader  # noqa: E402

from services.nar1_form import appearance as ap  # noqa: E402
from services.officer_change_form import nd2a_map as m  # noqa: E402
from services.officer_change_form import render, render_fields  # noqa: E402
from services.officer_changes import form_xml, nd2a_mapper  # noqa: E402
from tests.officer_changes import cr_fixtures as fx  # noqa: E402

COMPANY = "KANENAS HOLDING LIMITED"
FILED_ON = "2026-10-02"


@functools.lru_cache(maxsize=1)
def _xml():
    graph, entries = fx.combined_world("ND2A", fx.ND2A_OVERFLOW, fx.ND2A_OVERFLOW_RENAMES)
    return form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))


@functools.lru_cache(maxsize=1)
def rendered():
    return PdfReader(io.BytesIO(render("Nd2a", _xml(), company_name=COMPANY,
                                       submitted_on=FILED_ON)))


@functools.lru_cache(maxsize=1)
def filled():
    return PdfReader(io.BytesIO(render_fields("Nd2a", _xml(), company_name=COMPANY,
                                              submitted_on=FILED_ON)))


def runs(page):
    hits = []

    def visitor(text, cm, tm, font_dict, font_size):
        text = (text or "").rstrip("\r\n")
        face = str(font_dict.get("/BaseFont", "")) if font_dict else ""
        if text.strip() and any(name in face for name in ("Tinos", "NotoSerif")):
            hits.append((text, tm[4], tm[5], font_size, face))

    page.extract_text(visitor_text=visitor)
    return hits


def widget(field, page_index):
    for annot in filled().pages[page_index].get("/Annots") or []:
        obj = annot.get_object()
        if str(obj.get("/T") or "").split("__p")[0] == field:
            r = [float(v) for v in obj["/Rect"]]
            return min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])
    raise AssertionError(f"no {field} on page {page_index + 1}")


def drawn(field, page_index):
    x0, y0, x1, y1 = widget(field, page_index)
    inside = [r for r in runs(rendered().pages[page_index])
              if x0 - 1 <= r[1] <= x1 and y0 - 2 <= r[2] <= y1 + 2]
    assert inside, f"nothing drawn inside {field}"
    return sorted(inside, key=lambda r: -r[2])[0]


def test_every_drawn_run_is_in_our_embedded_faces():
    for page in rendered().pages:
        for annot in page.get("/Annots") or []:
            assert annot.get_object().get("/Subtype") != "/Widget"
    assert all(runs(p) for p in rendered().pages)


@pytest.mark.parametrize("field, page", [
    (m.MAIN_1["surname_en"], 0), (m.MAIN_1["hkid_partial"], 0),
    (m.MAIN_2["email"], 1), (m.MAIN_2["addr_street"], 1),
    (m.MAIN_3["name_en"], 2), (m.SHEET_A["surname_en"], 4),
    (m.SHEET_B["surname_en"], 6), (m.PI["hkid_full"], 8),
])
def test_values_are_bold_10pt(field, page):
    text, _x, _y, size, face = drawn(field, page)
    assert size == pytest.approx(10.0, abs=0.05), (field, text, size)
    assert "Bold" in face, (field, face)


def test_the_header_br_number_is_14pt_on_every_page():
    for index in range(len(rendered().pages)):
        page_no = int(str(next(
            str(a.get_object().get("/T")) for a in filled().pages[index].get("/Annots")
        )).split("__p")[0].split("P.")[1])
        field = {1: m.MAIN_1, 2: m.MAIN_2, 3: m.MAIN_3, 4: m.SHEET_A, 5: m.SHEET_B,
                 6: m.SHEET_C, 7: m.PI}[page_no]["br_number"]
        _t, _x, _y, size, _f = drawn(field, index)
        assert size == pytest.approx(14.0, abs=0.05), (index, size)


def test_the_company_name_is_12pt_and_centred():
    text, x, _y, size, face = drawn(m.MAIN_1["company_name"], 0)
    x0, _y0, x1, _y1 = widget(m.MAIN_1["company_name"], 0)
    width = ap.measure(text, size)
    assert size == pytest.approx(12.0, abs=0.05)
    assert x == pytest.approx(x0 + ((x1 - x0) - width) / 2, abs=0.6)


def test_the_presenter_block_is_regular_10pt():
    for key in ("presenter_name", "presenter_email"):
        _t, _x, _y, size, face = drawn(m.MAIN_1[key], 0)
        assert size == pytest.approx(10.0, abs=0.05) and "Bold" not in face, key
    # The Reference is one short line; a long company name is fitted down to
    # NAR1's 7pt floor (fill.PRESENTER_REFERENCE_MIN_SIZE), never truncated.
    text, _x, _y, size, face = drawn(m.MAIN_1["presenter_reference"], 0)
    assert 7.0 <= size <= 10.0 and "Bold" not in face
    assert text.startswith("ND2A/2022/")


@pytest.mark.parametrize("field, page", [
    (m.MAIN_1["surname_en"], 0), (m.MAIN_2["email"], 1), (m.MAIN_3["name_en"], 2),
    (m.PI["surname_en"], 8),
])
def test_a_left_value_starts_9_4pt_inside_its_box(field, page):
    _t, x, _y, _s, _f = drawn(field, page)
    x0, _y0, _x1, _y1 = widget(field, page)
    assert x == pytest.approx(x0 + 9.4, abs=0.3), field


@pytest.mark.parametrize("field, page", [
    (m.MAIN_1["hkid_partial"], 0), (m.MAIN_1["date_dd"], 0),
    (m.MAIN_3["own_br_number"], 2), (m.MAIN_3["count_pi"], 2),
    (m.MAIN_3["signed_date"], 2), (m.PI["hkid_full"], 8),
])
def test_centred_cells_are_centred(field, page):
    text, x, _y, size, face = drawn(field, page)
    x0, _y0, x1, _y1 = widget(field, page)
    width = ap.measure(text, size)
    assert x == pytest.approx(x0 + ((x1 - x0) - width) / 2, abs=0.6), (field, text)


@pytest.mark.parametrize("field, page", [
    (m.MAIN_1["surname_en"], 0), (m.MAIN_2["email"], 1), (m.MAIN_1["date_yyyy"], 0),
])
def test_a_single_line_sits_on_nar1s_baseline(field, page):
    _t, _x, y, size, _f = drawn(field, page)
    _x0, y0, _x1, y1 = widget(field, page)
    assert y == pytest.approx(y0 + ((y1 - y0) - 0.72 * size) / 2, abs=0.6), field
