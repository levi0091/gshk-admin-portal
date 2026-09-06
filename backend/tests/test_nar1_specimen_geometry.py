"""Typography and placement, measured off GSHK's own filed NAR1.

WHY THIS FILE EXISTS. The renderer used to take its point size from each
widget's `/DA` and its alignment from each widget's `/Q`. Both come out of the
blank fillable template, and neither is what CR's filing system prints:

  * 287 of the template's 298 text widgets carry an identical
    `/DA "/PMingLiU 12 Tf"` -- including the BR-number header, which CR prints
    at 14pt, and the presenter's block, which CR prints at 10pt in the REGULAR
    face. A default that is wrong in both directions is not a measurement.
  * `/Q 1` (centre) sits on the business name, the mortgages box, every
    officer's name and every address line -- all of which CR left-aligns.

So the numbers below were measured instead, on
`docs/Kanenas Holding Limited NAR1 2026.pdf`, by reading the advance of every
glyph CR drew and comparing it against the same string set in Tinos:

  * every ordinary value          Times New Roman **Bold, 10.0pt**
  * section 1, the company name   12.0pt
  * the BR number in each header  14.0pt
  * the presenter's block         10.0pt, REGULAR face
  * a left-aligned value starts   10.3pt inside the printed rule
  * a centred value is centred    on the printed box
  * the baseline of a single line y0 + (box height - 0.72 * size) / 2
  * a schedule's page number      the FOOTER's sans face at 8pt, not the
                                  return's Times bold

The per-glyph comparison also settles the other half of the client's report:
across 648 glyph advances on all nine pages, Tinos differs from CR's embedded
Times New Roman by at most 0.15pt and on average by 0.03pt -- which is the
rounding in CR's own `/Widths` array. The face was never wrong. The size was.
"""
import io

import pytest

pytest.importorskip("pypdf")
pytest.importorskip("pymupdf")
import pymupdf  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from services.nar1_form import appearance as ap  # noqa: E402
from services.nar1_form import field_map as fm  # noqa: E402
from services.nar1_form import fill  # noqa: E402
from tests.test_nar1_form_fill import build_xml  # noqa: E402


#: What CR leaves between the printed rule and the first glyph of a
#: left-aligned value. Measured over 30 values on pages 1, 2, 4, 5 and 8 of the
#: specimen: 10.32pt to 10.56pt, never anything else.
SPECIMEN_INSET = 10.4

#: The faces this renderer draws in, as they appear in an embedded subset's
#: /BaseFont ("ABCDEF+Tinos-Bold"). Anything else on the page is CR's own
#: printed template.
_OUR_FACES = ("Tinos", "NotoSerif", "Helvetica")


@pytest.fixture(scope="module")
def rendered():
    return PdfReader(io.BytesIO(fill.render(build_xml())))


def _runs(page):
    """Every run this renderer drew on `page`, as (text, x, y, size, face).

    Read out of the page's own content stream, so it is what a reader of the
    printed page sees rather than what a dict says should be there.
    """
    hits = []

    def visitor(text, cm, tm, font_dict, font_size):
        # pypdf ends every run it reports with a newline. Left on, it reaches
        # `ap.measure` and makes every width comparison in this file wrong by
        # half a character -- which is enough for a centred value to look
        # left-aligned and for the whole file to pass vacuously.
        text = (text or "").rstrip("\r\n")
        if not text.strip():
            return
        face = str(font_dict.get("/BaseFont", "")) if font_dict else ""
        if any(name in face for name in _OUR_FACES):
            hits.append((text, tm[4], tm[5], font_size, face))

    page.extract_text(visitor_text=visitor)
    return hits


def _widget(reader, field):
    """(page index, rect) for `field` on the rendered return."""
    for index, page in enumerate(reader.pages):
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if str(obj.get("/T") or "").split("__p")[0] == field:
                return index, [float(v) for v in obj["/Rect"]]
    raise AssertionError(f"no widget named {field!r} on the rendered return")


def drawn(reader, field):
    """The first run drawn inside `field`'s box: (text, x, y, size, face)."""
    index, rect = _widget(reader, field)
    x0, y0, x1, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), \
        max(rect[0], rect[2]), max(rect[1], rect[3])
    inside = [r for r in _runs(reader.pages[index])
              if x0 - 1 <= r[1] <= x1 and y0 - 2 <= r[2] <= y1 + 2]
    assert inside, f"nothing was drawn inside {field!r}"
    return sorted(inside, key=lambda r: -r[2])[0]


def box(reader, field):
    """`field`'s widget rectangle, normalised."""
    _, rect = _widget(reader, field)
    return (min(rect[0], rect[2]), min(rect[1], rect[3]),
            max(rect[0], rect[2]), max(rect[1], rect[3]))


def rule_left_of(pdf_bytes, reader, field):
    """The x of the printed rule this field's value sits inside.

    CR's inset is measured from the RULE, not from the widget rectangle, and
    the two are not the same thing: on this template /Rect sits 0.95pt inside
    its rule (measured over 284 widgets, standard deviation 0.15pt). Asserting
    against the rule is what makes the number here comparable with the number
    read off CR's own filed return, which carries no widgets at all.
    """
    index, rect = _widget(reader, field)
    page = pymupdf.open(stream=pdf_bytes, filetype="pdf")[index]
    height = page.rect.height
    x0, y0, y1 = min(rect[0], rect[2]), min(rect[1], rect[3]), \
        max(rect[1], rect[3])
    middle = (y0 + y1) / 2
    candidates = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.x - b.x) < 1.0 and abs(a.y - b.y) > 3:
                    lo, hi = height - max(a.y, b.y), height - min(a.y, b.y)
                    if a.x <= x0 + 1.0 and lo <= middle <= hi:
                        candidates.append(a.x)
            elif item[0] == "re" and item[1].height > 3:
                r = item[1]
                lo, hi = height - r.y1, height - r.y0
                if not lo <= middle <= hi:
                    continue
                # A rule is a filled rectangle about 0.9pt wide, and its LEFT
                # edge is the rule -- taking the right edge instead reads every
                # inset a rule-thickness short, which is the whole quantity
                # being measured. Only a real box contributes both edges.
                edges = (r.x0, r.x1) if r.width > 2.0 else (r.x0,)
                candidates += [e for e in edges if e <= x0 + 1.0]
    assert candidates, f"no printed rule found left of {field!r}"
    return max(candidates)


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

def test_an_ordinary_value_is_drawn_at_the_ten_points_CR_prints(rendered):
    """THE CLIENT'S REPORT: "the font looks smaller on the real form". It was.
    Every value drew at the template's `/DA` 12pt against CR's 10 -- a fifth
    too large, which beside the real return reads as a different typeface
    rather than a larger one."""
    for field in (fm.MAIN_1["ro_street"], fm.MAIN_1["business_name"],
                  fm.MAIN_2["mortgages_total"],
                  fm.share_capital(0, "total_amount"),
                  fm.DIRECTOR_INDIVIDUAL["surname_en"]):
        _, _, _, size, _ = drawn(rendered, field)
        assert size == 10.0, f"{field} drew at {size}pt, not CR's 10pt"


def test_the_company_name_is_twelve_point(rendered):
    _, _, _, size, _ = drawn(rendered, fm.MAIN_1["company_name"])
    assert size == 12.0


def test_the_BR_number_header_is_fourteen_point(rendered):
    _, _, _, size, _ = drawn(rendered, fm.MAIN_1["br_number"])
    assert size == 14.0


def test_the_presenter_block_is_ten_point_regular(rendered):
    """CR sets the presenter's block at the same 10pt as the return and
    distinguishes it by WEIGHT alone. Setting it a point smaller as well made
    the administrative note look like a footnote CR does not print."""
    text, _, _, size, face = drawn(rendered, fm.MAIN_1["presenter_name"])
    assert size == 10.0, f"the presenter's name drew at {size}pt, not 10pt"
    assert "Bold" not in face, f"the presenter's name drew in {face}"


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "ro_flat_floor_block", "ro_building", "ro_street", "ro_district",
    "business_name",
])
def test_a_left_aligned_value_starts_where_CR_starts_it(rendered, field):
    """10.3pt inside the printed rule -- not hard against it, and not the 2pt
    the renderer used, which put every address line visibly left of where the
    specimen puts it."""
    pdf = fill.render(build_xml())
    name = fm.MAIN_1[field]
    _, x, _, _, _ = drawn(rendered, name)
    rule = rule_left_of(pdf, rendered, name)
    assert x - rule == pytest.approx(SPECIMEN_INSET, abs=0.35), \
        f"{field} starts {x - rule:.2f}pt inside its rule, not {SPECIMEN_INSET}"


def test_an_officers_name_is_left_aligned_like_the_specimen(rendered):
    """The template quads this centre. CR does not: "ERIKSSON WASE" sits
    10.44pt inside the rule on page 5 of the specimen, and a centred name is
    the single most visible difference between the two documents."""
    left, _, right, _ = box(rendered, fm.DIRECTOR_INDIVIDUAL["surname_en"])
    text, x, _, size, _ = drawn(rendered, fm.DIRECTOR_INDIVIDUAL["surname_en"])
    centred = left + (right - left - ap.measure(text, size)) / 2
    assert x < centred - 20, \
        f"the director's surname drew centred (x={x:.1f}), not left"


def test_the_mortgages_box_is_left_aligned_like_the_specimen(rendered):
    """Section 9 on the specimen reads "Nil" against the left of a 492pt box.
    Ours centred it, which is the difference the client circled."""
    left, _, right, _ = box(rendered, fm.MAIN_2["mortgages_total"])
    text, x, _, size, _ = drawn(rendered, fm.MAIN_2["mortgages_total"])
    assert x < left + 20, f'"{text.strip()}" drew at x={x:.1f}, not left'


@pytest.mark.parametrize("field", [
    "return_date_dd", "return_date_mm", "return_date_yyyy",
])
def test_a_ruled_date_cell_is_centred(rendered, field):
    """The one group the template and CR agree on."""
    name = fm.MAIN_1[field]
    left, _, right, _ = box(rendered, name)
    text, x, _, size, _ = drawn(rendered, name)
    centred = left + (right - left - ap.measure(text, size)) / 2
    assert x == pytest.approx(centred, abs=0.5)


def test_a_share_capital_cell_is_centred_but_the_schedules_class_is_not(rendered):
    """The same word, "Ordinary", in two places CR treats differently: centred
    in section 11's table, left-aligned in Schedule 1's header. There is no
    rule to derive here -- it is CR's own layout, so it is measured and
    listed."""
    cell = fm.share_capital(0, "class")
    left, _, right, _ = box(rendered, cell)
    text, x, _, size, _ = drawn(rendered, cell)
    assert x == pytest.approx(
        left + (right - left - ap.measure(text, size)) / 2, abs=0.6)

    header = fm.SCHEDULE_1_HEADER["share_class"]
    left, _, right, _ = box(rendered, header)
    text, x, _, size, _ = drawn(rendered, header)
    assert x < left + 20, "Schedule 1's class of shares is left-aligned"


def test_the_signatory_name_and_date_are_centred(rendered):
    """BOTH are always drawn. The date box used to be allowed to come back
    empty, and this test skipped it when it did -- which is how a form whose
    Date box was blank on every return ever generated passed a suite that
    claimed to measure the signature block."""
    for field in ("signed_name", "signed_date"):
        name = fm.MEMBERS_AND_SIGNATURE[field]
        text, x, _, size, _ = drawn(rendered, name)
        left, _, right, _ = box(rendered, name)
        assert x == pytest.approx(
            left + (right - left - ap.measure(text, size)) / 2, abs=0.6)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["ro_street", "business_name"])
def test_a_single_line_sits_on_CRs_baseline(rendered, field):
    """CR centres the cap height in the box: y0 + (h - 0.72 * size) / 2.
    Measured against seven box heights on the specimen, from a 21.9pt date
    cell to the 107.9pt Total row, and it holds to 0.15pt in every one. The
    renderer added a further 0.06 * size on top, which lifted every value off
    CR's baseline by six tenths of a point."""
    name = fm.MAIN_1[field]
    x0, y0, x1, y1 = box(rendered, name)
    _, _, y, size, _ = drawn(rendered, name)
    assert y - y0 == pytest.approx((y1 - y0 - 0.72 * size) / 2, abs=0.2)


# ---------------------------------------------------------------------------
# The one value CR does not set in the return's face
# ---------------------------------------------------------------------------

def test_a_schedule_page_number_uses_the_footers_sans_face(rendered):
    """"附表一第 1 頁 Schedule 1 Page 1" is CR's page FOOTER, and CR fills its
    two numbers in the footer's own Arial 8pt regular rather than the return's
    Times bold. Ours drew them in 12pt bold serif, which is the only place on
    the form where the client's "the font family looks different" is literally
    true."""
    text, _, _, size, face = drawn(rendered, fm.SCHEDULE_1_PAGING["page_no"])
    assert size == 8.0, f"the schedule page number drew at {size}pt, not 8pt"
    assert "Helvetica" in face, \
        f"the schedule page number drew in {face}, not the footer's sans face"
