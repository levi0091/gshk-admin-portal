"""A director's drawn signature, printed on the rendered ND2A / ND2B
(e-signature-nd2, ticket 02; spec §4 and §6 test 6; technical review B1-B4).

The check is GEOMETRIC, as the NAR1 specimen tests are: render the form with
and without a signature, rasterise both with PyMuPDF, and require that every
pixel that differs lies inside the one rect the signature belongs in. A test
that only looked for "an image is somewhere on the page" would pass with the
signature printed over the typed name, which is exactly the defect the review
named (B2).
"""
import functools
import io

import pymupdf
import pytest
from PIL import Image, ImageChops, ImageDraw
from pypdf import PdfReader

from services.officer_change_form import nd2a_map, nd2b_map, render, stamp
from tests.officer_changes.test_nd2a_geometry import _xml as nd2a_xml
from tests.officer_changes.test_nd2b_form import overflow_xml as nd2b_xml

COMPANY = "KANENAS HOLDING LIMITED"
DPI = 144
SCALE = DPI / 72.0
NOISE = 24

# From the ND2A overflow world (`test_nd2a_geometry._xml`): the first natural
# appointment is a DIRECTOR (output page 2), the second a SECRETARY (Sheet B),
# the third a DIRECTOR (Sheet B); the signatory is "CHAN, TAI MAN".
FIRST = ("CHAN", "TAI MAN")
SECRETARY = ("HO", "KA YAN")
THIRD = ("WONG", "SIU MING")
SIGNATORY = "CHAN, TAI MAN"


def pad_png(size=(600, 200), bar=(400, 60)) -> bytes:
    """A pad's output: a mostly empty transparent canvas with one black stroke."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    left, top = (size[0] - bar[0]) // 2, (size[1] - bar[1]) // 2
    ImageDraw.Draw(img).rectangle([left, top, left + bar[0] - 1, top + bar[1] - 1],
                                  fill=(0, 0, 0, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


PNG = pad_png()


def sigs(*, consents=(), signatory=None) -> stamp.Signatures:
    return stamp.Signatures(
        consents={stamp.Signatures.key(*names): PNG for names in consents},
        signatory=(signatory, PNG) if signatory else None)


@functools.lru_cache(maxsize=None)
def _base(form):
    xml = nd2a_xml() if form == "Nd2a" else nd2b_xml()
    return xml, render(form, xml, company_name=COMPANY, submitted_on="2026-10-02")


def signed(form, signatures) -> bytes:
    xml, _ = _base(form)
    return render(form, xml, company_name=COMPANY, submitted_on="2026-10-02",
                  signatures=signatures)


def _pixmaps(pdf: bytes):
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    return [p.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB) for p in doc]


def changed_boxes(before: bytes, after: bytes) -> dict[int, tuple]:
    """`{page index: (x0, top, x1, bottom)}` in points, over the pixels that
    differ; pages that are unchanged do not appear.

    Re-serialising a page moves a few antialiased edge pixels by one or two
    levels of 255, which is not ink; only a difference of NOISE or more counts."""
    out = {}
    for index, (a, b) in enumerate(zip(_pixmaps(before), _pixmaps(after))):
        assert (a.width, a.height) == (b.width, b.height)
        diff = ImageChops.difference(Image.frombytes("RGB", (a.width, a.height), a.samples),
                                     Image.frombytes("RGB", (b.width, b.height), b.samples))
        box = diff.convert("L").point(lambda v: 255 if v > NOISE else 0).getbbox()
        if box:
            out[index] = tuple(v / SCALE for v in box)
    return out


def inside(box, rect, tol=1.0) -> bool:
    return (box[0] >= rect[0] - tol and box[1] >= rect[1] - tol
            and box[2] <= rect[2] + tol and box[3] <= rect[3] + tol)


def _template_widgets(template, page_number):
    doc = pymupdf.open(template)
    return {w.field_name: tuple(w.rect) for w in doc[page_number - 1].widgets()}


def _template_rules(template, page_number):
    """Thin horizontal black fills: the printed rules a signature sits on."""
    out = []
    for d in pymupdf.open(template)[page_number - 1].get_drawings():
        r = d["rect"]
        if r.height <= 1.1 and r.width > 150 and d.get("fill") == (0.0, 0.0, 0.0):
            out.append(tuple(r))
    return out


# -- the director's consent box (ND2A) -----------------------------------------------

def test_an_incoming_directors_signature_prints_in_their_consent_box_on_page_2():
    _, base = _base("Nd2a")
    boxes = changed_boxes(base, signed("Nd2a", sigs(consents=[FIRST])))
    assert list(boxes) == [1], "only page 2 changes"
    assert inside(boxes[1], stamp.ND2A_CONSENT_MAIN)
    # left-aligned, with the inset the typed values use, on the rule's side
    assert boxes[1][0] == pytest.approx(stamp.ND2A_CONSENT_MAIN[0] + stamp.INSET, abs=1.0)


def test_a_signature_prints_on_the_sheet_b_of_the_director_it_names():
    _, base = _base("Nd2a")
    boxes = changed_boxes(base, signed("Nd2a", sigs(consents=[THIRD])))
    # output order: 1 2 3 A A B(secretary) B(WONG) C PI PI PI
    assert list(boxes) == [6]
    assert inside(boxes[6], stamp.ND2A_CONSENT_SHEET_B)


def test_each_director_gets_their_own_box_and_no_other():
    _, base = _base("Nd2a")
    boxes = changed_boxes(base, signed("Nd2a", sigs(consents=[FIRST, THIRD])))
    assert sorted(boxes) == [1, 6]


def test_a_secretarys_consent_box_is_never_stamped():
    """Directors only: a secretary has no consent-to-act-as-director to sign."""
    _, base = _base("Nd2a")
    s = sigs(consents=[SECRETARY])
    assert signed("Nd2a", s) == base
    assert s.problems and "matches no director's consent" in s.problems[0]


def test_a_name_that_matches_no_box_stamps_nothing_and_is_reported():
    """Review B4: the frozen form can disagree with the live case. A signature is
    printed only where the page itself names the signer."""
    _, base = _base("Nd2a")
    s = sigs(consents=[("CHEUNG", "WING")])
    assert signed("Nd2a", s) == base
    assert len(s.problems) == 1


def test_names_are_matched_ignoring_case_and_spacing():
    _, base = _base("Nd2a")
    s = sigs(consents=[(" chan ", "tai   man")])
    assert list(changed_boxes(base, signed("Nd2a", s))) == [1]
    assert s.problems == []


def test_a_body_corporate_consent_signer_is_left_blank():
    """The consent signer there is an authorised person, not the appointee. Page
    3's body-corporate block carries no stamp except the form-level signature."""
    _, base = _base("Nd2a")
    boxes = changed_boxes(base, signed("Nd2a", sigs(consents=[FIRST, THIRD])))
    assert 2 not in boxes and 7 not in boxes


# -- the form-level signature, page 3 ---------------------------------------------------

@pytest.mark.parametrize("form, rect, template, number, name_field, last_page", [
    ("Nd2a", stamp.ND2A_SIGNATURE_P3,
     "ND2A_fillable.pdf", 3, nd2a_map.MAIN_3["signed_name"], 2),
    ("Nd2b", stamp.ND2B_SIGNATURE_P3,
     "ND2B_fillable.pdf", 3, nd2b_map.MAIN_3["signed_name"], 2),
])
def test_the_signatory_signs_above_the_typed_name_not_inside_it(
        form, rect, template, number, name_field, last_page):
    from services.officer_change_form import kit
    xml, base = _base(form)
    typed = "CHAN, TAI MAN"
    boxes = changed_boxes(base, signed(form, sigs(signatory=typed)))
    assert list(boxes) == [last_page]
    assert inside(boxes[last_page], rect)
    name_box = _template_widgets(kit.FORM_DIR / template, number)[name_field]
    # B2: strictly above the typed NAME box -- no overprint of the name
    assert boxes[last_page][3] <= name_box[1] + 0.01, (boxes[last_page], name_box)


def test_a_secretary_who_is_a_body_corporate_leaves_page_3_blank():
    """No natural-person signatory => the caller passes none => no change."""
    _, base = _base("Nd2a")
    assert signed("Nd2a", sigs()) == base


def test_a_signatory_name_that_is_not_the_typed_name_stamps_nothing():
    _, base = _base("Nd2a")
    s = sigs(signatory="SOMEONE ELSE")
    assert signed("Nd2a", s) == base
    assert any("signatory" in p for p in s.problems)


# -- nothing leaks, nothing changes ------------------------------------------------------

@pytest.mark.parametrize("form", ["Nd2a", "Nd2b"])
def test_with_no_signatures_the_output_is_byte_for_byte_today_s(form):
    xml, base = _base(form)
    again = render(form, xml, company_name=COMPANY, submitted_on="2026-10-02")
    assert signed(form, None) == base == again
    assert signed(form, stamp.Signatures()) == base


@pytest.mark.parametrize("form", ["Nd2a", "Nd2b"])
def test_stamping_adds_no_text_and_no_page(form):
    _, base = _base(form)
    out = signed(form, sigs(consents=[FIRST], signatory=SIGNATORY))
    a, b = PdfReader(io.BytesIO(base)), PdfReader(io.BytesIO(out))
    assert len(a.pages) == len(b.pages)
    assert [p.extract_text() for p in a.pages] == [p.extract_text() for p in b.pages]
    assert "/AcroForm" not in b.trailer["/Root"], "the stamped copy stays flat"


def test_the_default_render_never_stamps():
    """The send renders the draft with no `signatures` argument at all."""
    import inspect
    assert inspect.signature(render).parameters["signatures"].default is None


# -- the picture ----------------------------------------------------------------------------

def test_a_small_signature_is_never_enlarged_past_one_to_one():
    """40 x 10 px stays 40 x 10 pt, not stretched to fill a 350pt-wide box."""
    _, base = _base("Nd2a")
    s = stamp.Signatures(consents={stamp.Signatures.key(*FIRST): pad_png((60, 30), (40, 10))})
    box = changed_boxes(base, render("Nd2a", _base("Nd2a")[0], company_name=COMPANY,
                                     submitted_on="2026-10-02", signatures=s))[1]
    assert box[2] - box[0] == pytest.approx(40, abs=1.5)
    assert box[3] - box[1] == pytest.approx(10, abs=1.5)


def test_a_wide_signature_is_scaled_down_keeping_its_aspect_ratio():
    w, h = stamp.fit(400, 60, 100, 12)
    assert (w, h) == pytest.approx((80, 12))
    assert stamp.fit(50, 20, 300, 100) == (50, 20)


def test_the_margin_of_an_empty_pad_is_cropped_before_fitting():
    """A 600x200 pad with a stroke in the middle must print the STROKE at the
    size the box allows, not the margin."""
    _, base = _base("Nd2a")
    box = changed_boxes(base, signed("Nd2a", sigs(signatory=SIGNATORY)))[2]
    # the stroke is 400 x 60 (aspect 6.7) in a 12pt-tall box => about 80pt wide
    assert 60 < box[2] - box[0] < 100


def test_a_picture_that_cannot_be_read_is_reported_and_the_form_is_still_returned():
    _, base = _base("Nd2a")
    s = stamp.Signatures(consents={stamp.Signatures.key(*FIRST): b"not a png"})
    out = signed("Nd2a", s)
    assert out == base and s.problems


# -- the rects are the template's, not a guess --------------------------------------------------

@pytest.mark.parametrize("template, number, rect", [
    ("ND2A_fillable.pdf", 2, stamp.ND2A_CONSENT_MAIN),
    ("ND2A_fillable.pdf", 5, stamp.ND2A_CONSENT_SHEET_B),
])
def test_a_consent_rect_sits_on_its_printed_rule_and_covers_no_field(template, number, rect):
    from services.officer_change_form import kit
    path = kit.FORM_DIR / template
    rules = _template_rules(path, number)
    rule = next(r for r in rules if abs(r[0] - rect[0]) < 1 and abs(r[2] - rect[2]) < 1
                and 0 < r[1] - rect[3] <= 1.5)
    assert rule, "no printed rule under the rect"
    for name, w in _template_widgets(path, number).items():
        overlap_x = min(w[2], rect[2]) - max(w[0], rect[0])
        overlap_y = min(w[3], rect[3]) - max(w[1], rect[1])
        assert not (overlap_x > 0 and overlap_y > 0), f"{name} lies under the signature rect"


@pytest.mark.parametrize("template, rect, name_field", [
    ("ND2A_fillable.pdf", stamp.ND2A_SIGNATURE_P3, nd2a_map.MAIN_3["signed_name"]),
    ("ND2B_fillable.pdf", stamp.ND2B_SIGNATURE_P3, nd2b_map.MAIN_3["signed_name"]),
])
def test_the_page_3_rect_lies_above_the_name_box_and_over_no_widget(template, rect, name_field):
    from services.officer_change_form import kit
    widgets = _template_widgets(kit.FORM_DIR / template, 3)
    name = widgets[name_field]
    assert rect[3] <= name[1], "the signature area is ABOVE the typed name box (B2)"
    assert rect[0] >= name[0] - 3 and rect[2] <= name[2] + 3, "and over the same span"
    for field_name, w in widgets.items():
        overlap_x = min(w[2], rect[2]) - max(w[0], rect[0])
        overlap_y = min(w[3], rect[3]) - max(w[1], rect[1])
        assert not (overlap_x > 0 and overlap_y > 0), f"{field_name} lies under the rect"


# -- the whole path: stored pictures -> `for_form` -> the rendered form ----------------------

def test_stored_signatures_reach_the_boxes_of_the_people_who_drew_them(monkeypatch):
    """The names `for_form` derives from the PERSON must be the names the mapper
    printed in the form: if they drifted apart every signature would be reported
    as matching no box. Built from one world, so the two cannot disagree by
    construction of the test."""
    import base64

    from services import nar1_approvals
    from services.officer_changes import cases, form_xml, nd2a_mapper, signatures, signed_copies
    from tests.officer_changes import cr_fixtures as fx
    from tests.officer_changes.fakes import FakeSupabase

    graph, entries = fx.combined_world("ND2A", fx.ND2A_OVERFLOW, fx.ND2A_OVERFLOW_RENAMES)
    xml = form_xml.build("Nd2a", nd2a_mapper.map_case(graph, entries))
    directors = [e["person_id"] for e in entries
                 if e["kind"] == "appointment" and e.get("capacity") == "director"
                 and e.get("person_id")]
    secretary = graph["secretaries"][0]["person_id"]
    fake = FakeSupabase({
        "persons": list(graph["persons"].values()),
        "entities": [], "entity_officers": [],
        "company_secretaries": [{"id": "SEC", "entity_id": "E1", "person_id": secretary,
                                 "is_gshk": False, "is_current": True}],
        "officer_change_entries": [{**e, "case_id": "C1"} for e in entries],
        "officer_change_signatures": [
            {"id": f"S{n}", "case_id": "C1", "approval_id": f"A{n}", "person_id": pid,
             "revision": 1, "image_b64": base64.b64encode(PNG).decode()}
            for n, pid in enumerate([directors[0], directors[1], secretary])],
        "nar1_client_approvals": [],
    })
    for module in (cases, signatures, nar1_approvals):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    case = {"id": "C1", "entity_id": "E1", "form_code": "Nd2a", "client_approved": True,
            "verification_revision": 1}

    found = signed_copies.for_form(case)
    assert found is not None and found.signatory is not None
    unsigned = render("Nd2a", xml, company_name=COMPANY, submitted_on="2026-10-02")
    out = render("Nd2a", xml, company_name=COMPANY, submitted_on="2026-10-02",
                 signatures=found)
    assert found.problems == []
    boxes = changed_boxes(unsigned, out)
    # director 1 on page 2, director 2 on its Sheet B (index 6), the signatory on page 3
    assert sorted(boxes) == [1, 2, 6]
    assert inside(boxes[1], stamp.ND2A_CONSENT_MAIN)
    assert inside(boxes[2], stamp.ND2A_SIGNATURE_P3)
    assert inside(boxes[6], stamp.ND2A_CONSENT_SHEET_B)
