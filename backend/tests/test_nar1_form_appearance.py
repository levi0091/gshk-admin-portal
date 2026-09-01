"""The baked text layer: fonts, run splitting, fitting, and what it hides."""
import io

import pytest
from pypdf import PdfReader

from services.nar1_form import appearance as ap
from services.nar1_form import field_map as fm


def test_the_font_files_are_present_beside_the_module():
    """A font under docs/ is on one laptop and absent from Railway."""
    for name in ("Tinos-Bold.ttf", "Tinos-Regular.ttf", "NotoSerifTC-Bold.ttf"):
        assert (ap.FONT_DIR / name).exists(), f"{name} is missing"


def test_registering_fonts_twice_is_harmless():
    """Called per render; a second call must not raise."""
    ap.register_fonts()
    ap.register_fonts()


def test_latin_text_is_one_run_in_the_bold_face():
    ap.register_fonts()
    assert ap.split_runs("Kanenas Holding Limited") == [
        (ap.FONT_LATIN_BOLD, "Kanenas Holding Limited")
    ]


def test_cjk_text_is_one_run_in_the_cjk_face():
    ap.register_fonts()
    assert ap.split_runs("嘉寧斯控股有限公司") == [
        (ap.FONT_CJK, "嘉寧斯控股有限公司")
    ]


def test_a_mixed_value_splits_in_order_and_loses_nothing():
    """A Hong Kong address is routinely half English, half Chinese."""
    ap.register_fonts()
    runs = ap.split_runs("Suite C 中環 Hong Kong")
    assert [f for f, _ in runs] == [
        ap.FONT_LATIN_BOLD, ap.FONT_CJK, ap.FONT_LATIN_BOLD
    ]
    assert "".join(chunk for _, chunk in runs) == "Suite C 中環 Hong Kong"


def test_the_regular_face_is_selectable_for_the_presenter_block():
    ap.register_fonts()
    assert ap.split_runs("Get Started HK Limited", bold=False) == [
        (ap.FONT_LATIN, "Get Started HK Limited")
    ]


def test_empty_text_produces_no_runs():
    ap.register_fonts()
    assert ap.split_runs("") == []


def test_accented_latin_stays_in_the_latin_face():
    """The naive `not char.isascii()` test would sweep these into the CJK
    face. European directors are real in this book -- the reference return's
    director is Swedish -- so a Chinese font rendering "Åsa Öberg" is a live
    failure, not a hypothetical one."""
    ap.register_fonts()
    for name in ("Müller", "Ángel", "François", "Åsa Öberg", "İstanbul"):
        runs = ap.split_runs(name)
        assert [f for f, _ in runs] == [ap.FONT_LATIN_BOLD], \
            f"{name!r} did not stay in the Latin face"
        assert "".join(chunk for _, chunk in runs) == name


def test_a_value_mixing_accented_latin_and_cjk_splits_correctly():
    """Both fallbacks in one value, which is what a Hong Kong record of a
    European director actually looks like."""
    ap.register_fonts()
    runs = ap.split_runs("Müller 中環 Ángel")
    assert [f for f, _ in runs] == [
        ap.FONT_LATIN_BOLD, ap.FONT_CJK, ap.FONT_LATIN_BOLD
    ]
    assert "".join(chunk for _, chunk in runs) == "Müller 中環 Ángel"


# --- measuring and fitting -------------------------------------------------

def test_tinos_bold_is_metric_identical_to_times_new_roman(tmp_path):
    """The whole reason Tinos was chosen over shipping a Monotype font. If a
    future upgrade breaks this, values start wrapping differently and nobody
    would otherwise notice until a client complained again."""
    times = "C:/Windows/Fonts/timesbd.ttf"
    if not __import__("os").path.exists(times):
        pytest.skip("Times New Roman is a Windows font; not on this machine")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    ap.register_fonts()
    pdfmetrics.registerFont(TTFont("TimesBd-probe", times))
    for sample in ("Kanenas Holding Limited", "ERIKSSON WASE",
                   "Suite C, Level 7, World Trust Tower", "10,000.00"):
        ours = ap.measure(sample, 10.0)
        theirs = pdfmetrics.stringWidth(sample, "TimesBd-probe", 10.0)
        assert abs(ours - theirs) < 0.001, f"{sample!r} drifted"


def test_a_value_that_fits_keeps_its_nominal_size():
    ap.register_fonts()
    assert ap.fit_size("N/A", width=200.0) == 10.0


def test_an_overlong_value_is_shrunk_to_fit_not_clipped():
    """CR's boxes are fixed; an address that overflows must still be readable
    rather than run off the edge of the field.

    Width recalibrated from the brief's 90.0 to 200.0 (Task 3 implementation,
    2026-09-01): at 90.0 this 59-character value still measures 107.67pt at
    the 4.0pt floor -- 86pt usable -- so fit_size correctly returns the floor
    (the same clamp `test_shrinking_stops_at_a_legible_floor` exercises) and
    the "fits" assertion below can never hold, for any implementation, given
    the committed Tinos-Bold metrics. 200.0 lets the value actually converge
    above the floor (7.25pt), which is what this test means to demonstrate."""
    ap.register_fonts()
    long_value = "Flat A, 39/F, Block 2, Something Very Long Gardens, Kowloon"
    size = ap.fit_size(long_value, width=200.0)
    assert size < 10.0
    assert ap.measure(long_value, size) <= 200.0 - 4.0


def test_shrinking_stops_at_a_legible_floor():
    """Better a value that overflows visibly than one rendered at 2pt, which
    reads as a smudge and hides a wrong particular."""
    ap.register_fonts()
    assert ap.fit_size("x" * 400, width=20.0) == 4.0


# --- baking a document -----------------------------------------------------

def _baked():
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    return fill.render(build_xml())


def test_baking_clears_need_appearances():
    """The flag that made two viewers disagree."""
    reader = PdfReader(io.BytesIO(_baked()))
    acroform = reader.trailer["/Root"]["/AcroForm"]
    assert not acroform.get("/NeedAppearances")


def test_every_drawn_widget_is_hidden():
    """A visible widget paints its own box, and its own guess of the text,
    on top of the layer we just drew."""
    reader = PdfReader(io.BytesIO(_baked()))
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            if obj.get("/FT") != "/Tx":
                continue
            value = obj.get("/V")
            if value is None or not str(value).strip():
                continue
            assert int(obj.get("/F", 0)) & 2, \
                f"a valued widget is still visible: {obj.get('/T')}"


def test_both_latin_and_cjk_faces_are_embedded_when_both_are_used():
    """Non-embedded is how we got here: the viewer substitutes and the
    document changes shape by platform."""
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    reader = PdfReader(io.BytesIO(fill.render(
        build_xml(directors=("嘉寧斯控股有限公司",)))))
    found = {}
    for page in reader.pages:
        fonts = (page.get("/Resources") or {}).get("/Font")
        if not fonts:
            continue
        for value in fonts.get_object().values():
            value = value.get_object()
            base = str(value.get("/BaseFont"))
            descriptor = value.get("/FontDescriptor")
            if descriptor is None and value.get("/DescendantFonts"):
                descendant = value["/DescendantFonts"].get_object()[0]
                descriptor = descendant.get_object().get("/FontDescriptor")
            embedded = bool(descriptor) and any(
                key in descriptor.get_object()
                for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            if "Tinos" in base:
                found["latin"] = embedded
            if "NotoSerif" in base:
                found["cjk"] = embedded
    assert found.get("latin") is True, "the Latin face is missing or external"
    assert found.get("cjk") is True, "the CJK face is missing or external"


def test_the_pmingliu_default_no_longer_decides_anything():
    """Even if a stray /DA survives, no viewer should be reaching for it."""
    reader = PdfReader(io.BytesIO(_baked()))
    assert not reader.trailer["/Root"]["/AcroForm"].get("/NeedAppearances")


def test_a_chinese_name_survives_into_the_text_layer():
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    reader = PdfReader(io.BytesIO(fill.render(
        build_xml(directors=("嘉寧斯控股有限公司",)))))
    assert any("嘉寧斯" in (page.extract_text() or "") for page in reader.pages)


# ---------------------------------------------------------------------------
# C1 -- uncovered characters used to render BLANK, silently (final review)
# ---------------------------------------------------------------------------

def test_extension_b_is_routed_to_the_cjk_face():
    """The routing bug, isolated from font coverage: `_is_cjk` used to stop
    at U+9FFF, so every CJK Extension B character (U+20000-U+2FA1F) fell
    through to Tinos -- which carries 0 glyphs in that range -- instead of
    the CJK face, which may."""
    ap.register_fonts()
    char = "\U00020021"   # 𠀡, Extension B, one of 1,705 codepoints the
                          # currently-shipped NotoSerifTC-Bold.ttf carries
    assert ap.split_runs(char) == [(ap.FONT_CJK, char)]


def test_a_cjk_extension_b_character_renders_and_round_trips():
    """End to end: with the routing fixed, an Extension B character that the
    shipped CJK face actually carries survives into the rendered PDF's text
    layer rather than being drawn as glyph 0 (nothing)."""
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    char = "\U00020021"
    reader = PdfReader(io.BytesIO(fill.render(build_xml(directors=(char,)))))
    assert any(char in (page.extract_text() or "") for page in reader.pages)


def test_an_uncoverable_character_raises_rather_than_rendering_blank():
    """U+6768 (杨/楊, a top-ten Hong Kong surname) is CJK Unified -- routed to
    the CJK face correctly -- but is measured ABSENT from the currently
    shipped NotoSerifTC-Bold.ttf's cmap (a curated Subset build, not full CJK
    coverage). Before this fix reportlab silently mapped it to glyph 0 and
    drew nothing: no exception, no log line, a director's surname just gone
    from a statutory return. This asserts the render now refuses instead."""
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    char = "杨"
    with pytest.raises(fill.FormFillError, match=r"U\+6768"):
        fill.render(build_xml(directors=(char,)))


def test_draw_value_names_the_field_and_codepoint_in_the_error():
    """The lower-level contract `bake()` relies on: `draw_value` itself
    raises, naming both the offending character and which field it was on --
    not just 'something failed somewhere in a 15-page document'."""
    from reportlab.pdfgen import canvas as rl_canvas
    ap.register_fonts()
    buf = io.BytesIO()
    layer = rl_canvas.Canvas(buf, pagesize=(200.0, 50.0))
    with pytest.raises(ap.AppearanceError) as exc_info:
        ap.draw_value(layer, "杨", (0.0, 0.0, 100.0, 20.0),
                      field="fill_6_P.5")
    message = str(exc_info.value)
    assert "U+6768" in message
    assert "fill_6_P.5" in message


def test_draw_value_checks_every_run_before_drawing_any_of_them():
    """A mixed value with a good character followed by a bad one must not
    leave a half-drawn value on the page -- the check runs before any
    `drawString` call, not interleaved with them."""
    from reportlab.pdfgen import canvas as rl_canvas
    ap.register_fonts()
    buf = io.BytesIO()
    layer = rl_canvas.Canvas(buf, pagesize=(200.0, 50.0))
    with pytest.raises(ap.AppearanceError):
        ap.draw_value(layer, "OK 杨", (0.0, 0.0, 150.0, 20.0))
    assert buf.getvalue() == b""  # canvas.save() was never reached


def test_cmap_coverage_is_cached_not_rebuilt_per_character():
    """`_uncoverable` reads a set built once by `register_fonts()`, not the
    TTF's raw cmap dict on every character of every render."""
    ap.register_fonts()
    assert ap._CMAPS.get(ap.FONT_CJK)
    assert 0x4E2D in ap._CMAPS[ap.FONT_CJK]         # 中 -- every CJK render
                                                     # needs this to be there
    assert 0x6768 not in ap._CMAPS[ap.FONT_CJK]     # the measured DEV gap


def test_baking_does_not_bloat_the_attachment():
    """It has to survive a mail gateway. Subsetting is what keeps a 10MB CJK
    face from becoming 10MB of email."""
    assert len(_baked()) < 3_000_000


def test_every_page_header_carries_the_BRN_at_14pt():
    """CR prints it at 14pt on every page, not only the first. A header that
    silently falls back to 10pt is the kind of drift nobody reports and
    everybody notices."""
    from services.nar1_form import fill
    for group_name in ("MAIN_1", "MAIN_2", "SECRETARY_INDIVIDUAL",
                       "SECRETARY_CORPORATE", "DIRECTOR_INDIVIDUAL",
                       "DIRECTOR_CORPORATE_HEADER", "RESERVE_DIRECTOR",
                       "MEMBERS_AND_SIGNATURE"):
        group = getattr(fm, group_name)
        assert fill.FIELD_SIZES.get(group["br_number"]) == 14.0, \
            f"{group_name} header BRN is not 14pt"


def test_the_company_name_is_the_one_12pt_value():
    from services.nar1_form import fill
    assert fill.FIELD_SIZES[fm.MAIN_1["company_name"]] == 12.0


def test_every_br_number_in_field_map_is_registered_at_14pt():
    """CONFLICT B (final review): the ledger claimed 'Task 3 gains a test
    asserting every br_number in field_map is covered, so this cannot
    regress silently again' -- no such test existed.
    `test_every_page_header_carries_the_BRN_at_14pt` above enumerates 8 named
    groups by hand and omits both Schedule headers and all five Sheet
    headers, which is precisely what CONFLICT B was about. This makes the
    claim true: every dict-shaped attribute of `field_map` carrying a
    `br_number` key -- discovered by walking the module, not hand-listed --
    must be in `fill.FIELD_SIZES` at 14.0. The five sheet headers come from
    `_SHEET_HEADER`'s `{p}`-templated prototype, so they are expanded via
    `fm.sheet_header(page)` rather than skipped."""
    from services.nar1_form import fill
    checked = []
    for name in vars(fm):
        if name.startswith("_"):
            continue
        value = getattr(fm, name)
        if isinstance(value, dict) and "br_number" in value:
            checked.append(name)
            assert fill.FIELD_SIZES.get(value["br_number"]) == 14.0, \
                f"field_map.{name}['br_number'] is not registered at 14pt"
    for page in range(fm.PAGE_SHEET_A, fm.PAGE_SHEET_E + 1):
        head = fm.sheet_header(page)
        checked.append(f"sheet_header({page})")
        assert fill.FIELD_SIZES.get(head["br_number"]) == 14.0, \
            f"sheet_header({page})['br_number'] is not registered at 14pt"
    # The discovery itself has to find something, or this test would pass
    # vacuously if `field_map` were gutted.
    assert len(checked) >= 15, f"only found {checked!r} -- discovery broke"


# ---------------------------------------------------------------------------
# Caught by the visual gate, not by any assertion above (Task 6)
# ---------------------------------------------------------------------------

def test_a_centred_field_is_actually_centred():
    """CR sets /Q=1 on the company name and the BRN header, and its own filed
    returns render both centred in their boxes. Drawing every value hard
    against the left edge is visibly not CR's form -- and no test above could
    see it, because they all assert on values and fonts rather than position.
    """
    ap.register_fonts()
    rect = (0.0, 0.0, 200.0, 20.0)
    left = ap.draw_position("ABC", rect, size=10.0, quadding=0)
    centre = ap.draw_position("ABC", rect, size=10.0, quadding=1)
    right = ap.draw_position("ABC", rect, size=10.0, quadding=2)
    width = ap.measure("ABC", 10.0)
    assert left == 2.0
    assert abs(centre - (200.0 - width) / 2) < 0.01
    assert abs(right - (200.0 - 2.0 - width)) < 0.01
    assert left < centre < right


def test_quadding_falls_back_to_left_when_the_field_does_not_say():
    """Most of CR's fields carry no /Q at all; those are left-aligned."""
    ap.register_fonts()
    rect = (0.0, 0.0, 200.0, 20.0)
    assert ap.draw_position("ABC", rect, size=10.0, quadding=None) == 2.0


def test_the_company_name_and_BRN_are_centred_on_the_rendered_form():
    """The two fields CR quads centre, checked end to end rather than in
    isolation -- this is what the reference return shows."""
    import io as _io
    from pypdf import PdfReader as _R
    from services.nar1_form import fill
    from services.nar1_form import field_map as fm
    from tests.test_nar1_form_fill import build_xml
    reader = _R(_io.BytesIO(fill.render(build_xml())))
    centred = {fm.MAIN_1["company_name"], fm.MAIN_1["br_number"]}
    seen = 0
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            name = str(obj.get("/T") or "").split("__p")[0]
            if name in centred:
                assert int(obj.get("/Q", 0)) == 1, f"{name} lost its quadding"
                seen += 1
    assert seen >= 2, "expected the company name and the BRN header"


def _field_rect(reader, page_index, field_name):
    """The widget rectangle CR laid out for `field_name` on `reader`'s page
    `page_index`, read back from the rendered document's own AcroForm --
    not assumed, so a template change cannot make this test drift silently."""
    page = reader.pages[page_index]
    for annot in page.get("/Annots") or []:
        obj = annot.get_object()
        name = str(obj.get("/T") or "").split("__p")[0]
        if name == field_name:
            return [float(v) for v in obj["/Rect"]]
    raise AssertionError(f"field {field_name!r} not found on page {page_index}")


def _drawn_runs(page, needle):
    """Every piece of text drawn on `page` containing `needle`, as
    (text, x, font_size, base_font) -- read straight out of the page's own
    content stream via pypdf's visitor callback, per the PDF spec's
    `(text, cm, tm, font_dict, font_size)` signature. `tm[4]` is the x the
    text was actually positioned at; `font_dict['/BaseFont']` names the face
    actually used to draw it. This is independent of every value- and
    dict-level assertion elsewhere in this file."""
    hits = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text and needle in text:
            base = font_dict.get("/BaseFont") if font_dict else None
            hits.append((text, tm[4], font_size, str(base)))

    page.extract_text(visitor_text=visitor)
    return hits


def test_the_baked_fidelity_wiring_is_actually_applied():
    """I2 (final review): `sizes=FIELD_SIZES`, `regular=REGULAR_WEIGHT_FIELDS`
    and `quadding=obj.get('/Q')` were removed from the `bake()` call in
    `fill._render` -- reverting every fidelity decision Tasks 3 and 6 made --
    and 63 tests still passed. Every one of them asserted on FIELD_SIZES'
    contents, REGULAR_WEIGHT_FIELDS membership, or draw_position's arithmetic
    IN ISOLATION; `test_the_company_name_and_BRN_are_centred_on_the_rendered_
    form` reads the widget's `/Q`, which is the TEMPLATE's, not the one the
    renderer was told to honour. None of them read what was actually drawn.

    This one does, for all three: the BRN's drawn size, the company name's
    drawn x against an independently computed centred position, and the
    presenter block's drawn face."""
    from services.nar1_form import fill
    from services.nar1_form import field_map as fm2
    from tests.test_nar1_form_fill import build_xml

    pdf = fill.render(build_xml())
    reader = PdfReader(io.BytesIO(pdf))
    page1 = reader.pages[0]

    # 1) The BRN header is drawn at CR's 14pt, not the 10pt default.
    br_runs = _drawn_runs(page1, "T0001137")
    assert br_runs, "the BRN was not found in page 1's drawn text"
    _, _br_x, br_size, _br_font = br_runs[0]
    assert br_size == 14.0, f"the BRN drew at {br_size}pt, not CR's 14pt"

    # 2) The company name is drawn CENTRED -- its x matches an independently
    # computed centred position, not the plain left pad.
    name_runs = _drawn_runs(page1, "TEST COMPANY LIMITED")
    assert name_runs, "the company name was not found in page 1's drawn text"
    _, name_x, name_size, _name_font = name_runs[0]
    full_name = "TEST COMPANY LIMITED  測試有限公司"     # what fill._company_name
                                                          # actually joins
    rect = _field_rect(reader, 0, fm2.MAIN_1["company_name"])
    left_pad = rect[0] + 2.0
    centred_x = ap.draw_position(full_name, rect, size=name_size, quadding=1,
                                 bold=True)
    assert abs(name_x - left_pad) > 5.0, \
        f"the company name drew hard against the left pad ({left_pad}) " \
        f"instead of centred"
    assert abs(name_x - centred_x) < 0.5, \
        f"the company name drew at x={name_x}, not the centred x={centred_x}"

    # 3) The presenter block is drawn in the REGULAR face, not bold.
    presenter_runs = _drawn_runs(page1, "Get Started HK Limited")
    assert presenter_runs, "the presenter name was not found in page 1's drawn text"
    _, _pres_x, _pres_size, presenter_font = presenter_runs[0]
    assert "Bold" not in presenter_font, \
        f"the presenter block drew in {presenter_font!r}, not the regular face"


def test_the_presenter_block_is_regular_weight_not_bold():
    """CR's own return sets the presenter's details in Times New Roman
    REGULAR while every statutory value above it is bold. Rendering the whole
    page bold loses the distinction CR draws between the return's content and
    the administrative block identifying who filed it."""
    from services.nar1_form import fill
    from services.nar1_form import field_map as fm
    for key in ("presenter_name", "presenter_address", "presenter_tel",
                "presenter_fax", "presenter_email", "presenter_reference"):
        assert fm.MAIN_1[key] in fill.REGULAR_WEIGHT_FIELDS, \
            f"{key} should render in the regular face"
    assert fm.MAIN_1["company_name"] not in fill.REGULAR_WEIGHT_FIELDS


def test_a_regular_weight_run_uses_the_regular_face():
    ap.register_fonts()
    assert ap.split_runs("Get Started HK Limited", bold=False) == [
        (ap.FONT_LATIN, "Get Started HK Limited")
    ]


def test_the_baked_layer_uses_no_deprecated_pypdf_path():
    """`pypdf` is declared `>=6.16.1` with no upper bound, so a routine
    `uv sync` can resolve 7.0 and this renderer must still work then.

    pypdf 6.16 deprecates merging onto a page that is not attached to a
    writer -- its own note says "the existing approach has proved being
    unreliable" -- and removes it in 7.0. Without this test the failure mode
    is a dependency bump that silently stops every client-verification email
    from rendering its attachment.
    """
    import warnings
    from tests.test_nar1_form_fill import build_xml
    from services.nar1_form import fill
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        fill.render(build_xml())
