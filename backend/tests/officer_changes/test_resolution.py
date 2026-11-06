"""The written resolution (`services/officer_changes/resolution.py`), to GSHK's
2026-11-06 template (`Template - Written Resolutions.pdf`).

Geometry is the first sample's (Word, US Letter, Times 12) and is unchanged by
the template: header baselines 112.9 128.8 144.6 160.5, headings at 206.1 and
291.4, body 234.0 / 250.0 and 319.4 / 335.2. What the template changed is the
words, the header's BR line, the absent closing sentence (so "Dated" now follows
the last paragraph by two blank lines, at 376.7), and the signature block: two
columns at x 72 and x 360, every director before the changes plus every director
appointed. Neither PDF is committed: they name real companies and directors.
"""
import io

import pymupdf
import pytest
from PIL import Image, ImageChops, ImageDraw

from services.officer_changes import resolution

TOL = 0.6

CASE = {"id": "K1", "case_no": "ND2A-2026-0007", "form_code": "Nd2a"}
ENTITY = {"company_name": "ZenithStream Limited", "br_number": "75092262"}
OFFICERS = [
    {"officer_id": "O1", "role": "director", "name": "PIK YI REBECCA LAW", "name_zh": "羅碧儀",
     "person_id": "P1"},
    {"officer_id": "O3", "role": "company_secretary", "name": "Get Started HK Limited"},
]
RESIGN = {"id": "N1", "kind": "cessation", "capacity": "director", "officer_id": "O1",
          "cessation_reason": "R", "effective_date": "2026-03-20",
          "party": {"name": "PIK YI REBECCA LAW", "name_zh": "羅碧儀"}}
APPOINT = {"id": "N2", "kind": "appointment", "capacity": "director",
           "effective_date": "2026-03-20", "party": {"name": "Aldo KRIEL", "name_zh": "歐立德"}}
SAMPLE = [RESIGN, APPOINT]


def _pages(pdf: bytes):
    return list(pymupdf.open(stream=pdf, filetype="pdf"))


def _lines(page) -> list[dict]:
    """[{text, y (baseline), x0, fonts, size}] — one per visual line."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            out.append({"text": "".join(s["text"] for s in line["spans"]).strip(),
                        "y": round(spans[0]["origin"][1], 2), "x0": spans[0]["bbox"][0],
                        "x1": spans[-1]["bbox"][2],
                        "fonts": {s["font"] for s in spans}, "size": spans[0]["size"]})
    return sorted(out, key=lambda r: (r["y"], r["x0"]))


def _line(page, starts: str) -> dict:
    found = [r for r in _lines(page) if r["text"].startswith(starts)]
    assert found, f"no line starting {starts!r}: {[r['text'] for r in _lines(page)]}"
    return found[0]


def _text(pdf: bytes) -> str:
    return " ".join(" ".join(p.get_text().split()) for p in _pages(pdf))


@pytest.fixture(scope="module")
def sample_page():
    return _pages(resolution.render(CASE, ENTITY, SAMPLE, OFFICERS))[0]


def test_page_is_us_letter(sample_page):
    assert (sample_page.rect.width, sample_page.rect.height) == (612, 792)


def test_header_rules_match_the_sample(sample_page):
    rules = sorted((d["rect"] for d in sample_page.get_drawings()
                    if d["rect"].width > 400), key=lambda r: r.y0)
    assert len(rules) == 2
    for rule, top in zip(rules, (86.42, 179.54)):
        assert abs(rule.y0 - top) < TOL and abs(rule.height - 1.44) < 0.05
        assert abs(rule.x0 - 70.58) < TOL and abs(rule.x1 - 541.53) < TOL


def test_header_lines_are_bold_centred_at_the_sample_baselines(sample_page):
    for text, y in (("WRITTEN RESOLUTIONS OF", 112.9), ("ZenithStream Limited", 128.8),
                    ("(Business License No. 75092262)", 144.6),
                    ("(the “Company”)", 160.5)):
        line = _line(sample_page, text)
        assert line["text"] == text
        assert abs(line["y"] - y) < TOL, (text, line["y"])
        assert all("Bold" in f for f in line["fonts"]) and line["size"] == 12
        assert abs((line["x0"] + line["x1"]) / 2 - 306) < 1.0, text


def test_body_flows_at_the_sample_baselines(sample_page):
    for starts, y in (("Resignation of Director", 206.1),
                      ("IT IS RESOLVED that PIK YI REBECCA LAW", 234.0),
                      ("Appointment of Director", 291.4),
                      ("IT IS RESOLVED that the company shall appoint Aldo KRIEL", 319.4),
                      ("Dated:", 376.7),
                      ("____", 445.7), ("Name: PIK YI REBECCA LAW", 459.8),
                      ("Director", 475.8)):
        line = _line(sample_page, starts)
        assert abs(line["y"] - y) < TOL, (starts, line["y"], y)
    # Second lines of the two-line paragraphs (Word's taller line after Chinese).
    ys = [r["y"] for r in _lines(sample_page)]
    for y in (250.0, 335.2):
        assert any(abs(v - y) < TOL for v in ys), y


def test_body_is_times_12_regular_and_headings_bold_underlined(sample_page):
    body = _line(sample_page, "IT IS RESOLVED that the company shall appoint")
    # Regular Times, with only the officer's name in bold (checked separately).
    assert body["size"] == 12 and any("Bold" not in f and "Tinos" in f for f in body["fonts"])
    assert abs(body["x0"] - 72) < TOL
    heading = _line(sample_page, "Resignation of Director")
    assert all("Bold" in f for f in heading["fonts"])
    underline = [d["rect"] for d in sample_page.get_drawings()
                 if d["rect"].width < 400 and abs(d["rect"].y0 - 207.38) < TOL]
    assert underline and abs(underline[0].x0 - 72) < TOL
    assert abs(underline[0].x1 - heading["x1"]) < 4  # under the words, not the margin


def test_chinese_names_print_in_noto_sans_tc(sample_page):
    spans = [s for b in sample_page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             for s in ln["spans"] if "羅碧儀" in s["text"] or "歐立德" in s["text"]]
    assert spans and all("NotoSansTC" in s["font"] for s in spans)
    assert all(s["size"] == 12 for s in spans)


def test_signature_blocks_sit_in_the_templates_two_columns(sample_page):
    """The first director (the one resigning) is the left block, the one
    appointed the right: rows of two, left x 72, right x 360."""
    rows = [r for r in _lines(sample_page) if r["y"] > 440]
    left = [r for r in rows if r["x0"] < 200]
    right = [r for r in rows if r["x0"] > 300]
    assert [r["text"][:4] for r in left] == ["____", "Name", "Dire"]
    assert [r["text"][:4] for r in right] == ["____", "Name", "Dire"]
    assert all(abs(r["x0"] - 72.0) < TOL for r in left)
    assert all(abs(r["x0"] - 360.0) < TOL for r in right)
    # one row: each column's rule shares a baseline
    assert abs(left[0]["y"] - right[0]["y"]) < 0.01
    assert left[1]["text"].startswith("Name: PIK YI REBECCA LAW")
    assert right[1]["text"].startswith("Name: Aldo KRIEL")


def test_the_templates_wording():
    out = _text(resolution.render(CASE, ENTITY, SAMPLE, OFFICERS))
    assert ("IT IS RESOLVED that PIK YI REBECCA LAW 羅碧儀 shall resign as director from the "
            "company effective from the date hereof.") in out
    assert ("IT IS RESOLVED that the company shall appoint Aldo KRIEL 歐立德 as its new "
            "director effective from the date hereof.") in out
    assert "of the company effective" not in out, "the R-1 wording is superseded"
    assert "Dated: 20 March 2026" in out
    # The director resigning signs, as does the one appointed (the template's point).
    assert "Name: PIK YI REBECCA LAW 羅碧儀" in out and "Name: Aldo KRIEL 歐立德" in out


def test_there_is_no_closing_sentence():
    for entries in ([APPOINT], SAMPLE, SAMPLE + [{**APPOINT, "id": "N3"}]):
        out = _text(resolution.render(CASE, ENTITY, entries, OFFICERS))
        assert "filed and submitted" not in out and "shall also be filed" not in out
    assert not hasattr(resolution, "closing")


def test_three_changes_share_a_plural_heading():
    second = {**APPOINT, "id": "N3", "party": {"name": "HO New"}}
    out = _text(resolution.render(CASE, ENTITY, SAMPLE + [second], OFFICERS))
    assert "Appointment of Directors" in out


def test_the_officers_name_is_bold_inside_the_sentence(sample_page):
    spans = [s for b in sample_page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             for s in ln["spans"]]
    bold = " ".join(s["text"] for s in spans
                    if "Bold" in s["font"] and not s["text"].startswith("Resignation")
                    and not s["text"].startswith("Appointment"))
    assert "Aldo KRIEL" in bold and "PIK YI REBECCA LAW" in bold
    lead = [s for s in spans if s["text"].startswith("IT IS RESOLVED that")]
    assert lead and all("Bold" not in s["font"] for s in lead)


def test_header_has_the_chinese_name_on_its_own_line_and_the_br_line():
    entity = {**ENTITY, "company_name_zh": "天流有限公司"}
    page = _pages(resolution.render(CASE, entity, SAMPLE, OFFICERS))[0]
    texts = [r["text"] for r in _lines(page) if r["y"] < 190]
    assert texts == ["WRITTEN RESOLUTIONS OF", "ZenithStream Limited", "天流有限公司",
                     "(Business License No. 75092262)", "(the “Company”)"]


def test_header_leaves_out_the_br_line_when_there_is_no_number():
    entity = {"company_name": "ZenithStream Limited"}
    page = _pages(resolution.render(CASE, entity, SAMPLE, OFFICERS))[0]
    texts = [r["text"] for r in _lines(page) if r["y"] < 190]
    assert texts == ["WRITTEN RESOLUTIONS OF", "ZenithStream Limited", "(the “Company”)"]


def test_a_secretary_is_worded_as_a_secretary():
    entries = [{"id": "N1", "kind": "cessation", "capacity": "company_secretary",
                "officer_id": "O3", "cessation_reason": "R", "effective_date": "2026-03-20",
                "party": {"name": "Get Started HK Limited"}},
               {"id": "N2", "kind": "appointment", "capacity": "company_secretary",
                "effective_date": "2026-03-20", "party": {"name": "Island Secretaries Limited"}}]
    out = _text(resolution.render(CASE, ENTITY, entries, OFFICERS))
    assert "Resignation of Company Secretary" in out and "Appointment of Company Secretary" in out
    assert ("IT IS RESOLVED that Get Started HK Limited shall resign as company secretary "
            "from the company effective from the date hereof.") in out
    assert ("IT IS RESOLVED that the company shall appoint Island Secretaries Limited as its "
            "new company secretary effective from the date hereof.") in out


def test_a_death_is_noted_not_resolved():
    dead = {**RESIGN, "cessation_reason": "D"}
    out = _text(resolution.render(CASE, ENTITY, [dead, APPOINT], OFFICERS))
    assert "Cessation of Director" in out
    assert ("IT IS NOTED that PIK YI REBECCA LAW 羅碧儀 ceased to be a director of the "
            "company by reason of death.") in out


def test_dated_uses_a_two_digit_day():
    early = {**APPOINT, "effective_date": "2026-11-04"}
    assert "Dated: 04 November 2026" in _text(resolution.render(CASE, ENTITY, [early], OFFICERS))
    assert resolution.dated([early]) == "04 November 2026"


def test_dated_is_left_blank_when_the_dates_differ_or_are_missing():
    later = {**APPOINT, "effective_date": "2026-03-21"}
    assert "Dated: ____" in _text(resolution.render(CASE, ENTITY, [RESIGN, later], OFFICERS))
    undated = {**APPOINT, "effective_date": None}
    assert "Dated: ____" in _text(resolution.render(CASE, ENTITY, [undated], OFFICERS))


def test_every_director_before_and_every_director_appointed_signs():
    officers = OFFICERS + [{"officer_id": "O4", "role": "director", "name": "CHAN Tai Man",
                            "person_id": "P4"}]
    page = _pages(resolution.render(CASE, ENTITY, SAMPLE, officers))[0]
    names = [r["text"] for r in _lines(page) if r["text"].startswith("Name:")]
    # Row-major, two to a row: the board before (resigning director included), then the new.
    assert names == ["Name: PIK YI REBECCA LAW 羅碧儀", "Name: CHAN Tai Man",
                     "Name: Aldo KRIEL 歐立德"]


def test_a_body_corporate_director_signs_for_and_on_behalf_of():
    corp = {"officer_id": "O5", "role": "director", "name": "Acme Holdings Limited",
            "party_type": "corporate", "corporate_entity_id": "C5"}
    pdf = resolution.render(CASE, ENTITY, [APPOINT], [corp])
    out = _text(pdf)
    assert "Name: Acme" not in out, "'Name:' is left blank for the signing individual"
    page = _pages(pdf)[0]
    dated_y = _line(page, "Dated:")["y"]
    lines = [r["text"] for r in _lines(page) if r["x0"] < 200 and r["y"] > dated_y]
    assert lines == ["_" * 29, "Name:", "For and on behalf of", "Acme Holdings Limited",
                     "Director"]


def test_a_director_is_one_line_even_when_listed_twice():
    officers = OFFICERS + [{"officer_id": "O9", "role": "director", "name": "PIK YI REBECCA LAW",
                            "person_id": "P1"}]
    assert resolution.signatories([], officers) == ["PIK YI REBECCA LAW 羅碧儀"]


def test_a_director_who_has_died_has_no_line():
    dead = {**RESIGN, "cessation_reason": "D"}
    assert resolution.signatories([dead, APPOINT], OFFICERS) == ["Aldo KRIEL 歐立德"]


def test_alternate_directors_are_worded_and_do_not_sign():
    alt_in = {"id": "N7", "kind": "appointment", "capacity": "alternate_director",
              "effective_date": "2026-03-20", "alternate_to_name": "PIK YI REBECCA LAW",
              "party": {"name": "Zed ALTERNATE"}}
    alt_out = {"id": "N8", "kind": "cessation", "capacity": "alternate_director",
               "officer_id": "O8", "cessation_reason": "R", "effective_date": "2026-03-20",
               "alternate_to_name": "PIK YI REBECCA LAW", "party": {"name": "Old ALTERNATE"}}
    officers = OFFICERS + [{"officer_id": "O8", "role": "alternate_director",
                            "name": "Old ALTERNATE", "person_id": "P8"}]
    out = _text(resolution.render(CASE, ENTITY, [alt_out, alt_in], officers))
    assert "Appointment of Alternate Director" in out
    assert "Resignation of Alternate Director" in out
    assert ("IT IS RESOLVED that the company shall appoint Zed ALTERNATE as alternate director "
            "to PIK YI REBECCA LAW effective from the date hereof.") in out
    assert ("IT IS RESOLVED that Old ALTERNATE shall resign as alternate director to "
            "PIK YI REBECCA LAW from the company effective from the date hereof.") in out
    assert "Name: Zed" not in out and "Name: Old" not in out
    assert resolution.signatories([alt_out, alt_in], officers) == ["PIK YI REBECCA LAW 羅碧儀"]


def test_a_long_board_breaks_onto_a_second_page():
    officers = [{"officer_id": f"O{n}", "role": "director", "name": f"DIRECTOR Number {n}"}
                for n in range(10, 22)]
    pages = _pages(resolution.render(CASE, ENTITY, [APPOINT], officers))
    assert len(pages) >= 2
    for page in pages:
        assert all(r["y"] < 792 - 60 for r in _lines(page))


def test_a_long_company_name_wraps_inside_the_rules():
    entity = {**ENTITY, "company_name": "The Extraordinarily Long Name International "
                                        "Holdings and Investments Company Limited"}
    page = _pages(resolution.render(CASE, entity, SAMPLE, OFFICERS))[0]
    rules = sorted((d["rect"] for d in page.get_drawings() if d["rect"].width > 400),
                   key=lambda r: r.y0)
    header = [r for r in _lines(page) if rules[0].y0 < r["y"] < rules[1].y0]
    assert len(header) == 5 and all(r["x1"] < 541.53 and r["x0"] > 70.58 for r in header)


def test_signatories_are_the_board_before_plus_the_appointed():
    assert resolution.signatories(SAMPLE, OFFICERS) == ["PIK YI REBECCA LAW 羅碧儀",
                                                         "Aldo KRIEL 歐立德"]


def test_file_name():
    assert resolution.file_name(CASE) == "Written-Resolution-ND2A-2026-0007.pdf"


def test_a_signature_block_is_never_split_across_pages():
    """Review finding 4: six changes pushed the first block's 'Director' line
    alone onto page 2. A block is the rule, the name and 'Director', together."""
    officers = [{"officer_id": f"O{n}", "role": "director", "name": f"OUTGOING Number {n}"}
                for n in range(1, 4)] + [
        {"officer_id": "O9", "role": "director", "name": "STAYING Director"}]
    entries = [{"id": f"C{n}", "kind": "cessation", "capacity": "director", "officer_id": f"O{n}",
                "cessation_reason": "R", "effective_date": "2026-03-20",
                "party": {"name": f"OUTGOING Number {n}"}} for n in range(1, 4)] + [
        {"id": f"A{n}", "kind": "appointment", "capacity": "director",
         "effective_date": "2026-03-20", "party": {"name": f"INCOMING Number {n}"}}
        for n in range(1, 4)]
    for page in _pages(resolution.render(CASE, ENTITY, entries, officers)):
        texts = [r["text"] for r in _lines(page)]
        rules = sum(t.startswith("____") for t in texts)
        names = sum(t.startswith("Name:") for t in texts)
        labels = sum(t == "Director" for t in texts)
        assert rules == names == labels, (rules, names, labels)


# -- directors' drawn signatures (e-signature-nd2, ticket 02; spec §4, §6 test 6) -----------

def _stroke_png() -> bytes:
    img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([100, 70, 499, 129], fill=(0, 0, 0, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _two_directors_world():
    """Two directors stay, one leaves and one is appointed: four signature lines
    (the one leaving still signs: the template lists everyone in office before)."""
    officers = [{"officer_id": "O1", "role": "director", "name": "STAYING One",
                 "person_id": "P1"},
                {"officer_id": "O2", "role": "director", "name": "STAYING Two",
                 "person_id": "P2"},
                {"officer_id": "O3", "role": "director", "name": "LEAVING Three",
                 "person_id": "P3"}]
    entries = [{"id": "C1", "kind": "cessation", "capacity": "director", "officer_id": "O3",
                "person_id": "P3", "cessation_reason": "R", "effective_date": "2026-03-20",
                "party": {"name": "LEAVING Three"}},
               {"id": "A1", "kind": "appointment", "capacity": "director",
                "person_id": "P4", "effective_date": "2026-03-20",
                "party": {"name": "INCOMING Four"}}]
    return entries, officers


def _ink_boxes(before: bytes, after: bytes, dpi=144):
    """Changed-pixel bbox in points per page, ignoring re-serialisation noise."""
    out = {}
    scale = dpi / 72.0
    for i, (a, b) in enumerate(zip(_pages(before), _pages(after))):
        pa, pb = (p.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB) for p in (a, b))
        diff = ImageChops.difference(Image.frombytes("RGB", (pa.width, pa.height), pa.samples),
                                     Image.frombytes("RGB", (pb.width, pb.height), pb.samples))
        box = diff.convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
        if box:
            out[i] = tuple(v / scale for v in box)
    return out


def test_signatories_come_with_their_person_ids_in_the_same_order():
    entries, officers = _two_directors_world()
    assert resolution.signatory_people(entries, officers) == [
        ("STAYING One", "P1"), ("STAYING Two", "P2"), ("LEAVING Three", "P3"),
        ("INCOMING Four", "P4")]
    assert resolution.signatories(entries, officers) == [
        n for n, _ in resolution.signatory_people(entries, officers)]


def _rules(pdf: bytes) -> list[tuple[int, dict]]:
    """Every signature rule in the document, as (page index, line), in order."""
    return [(i, r) for i, page in enumerate(_pages(pdf)) for r in _lines(page)
            if r["text"].startswith("____")]


def test_a_signed_directors_image_prints_above_their_own_rule_only():
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    signed = resolution.render(CASE, ENTITY, entries, officers,
                               signatures={"P2": _stroke_png()})
    boxes = _ink_boxes(base, signed)
    rules = _rules(base)
    assert len(rules) == 4
    page_no, rule = rules[1]                          # STAYING Two: row 1, right column
    assert list(boxes) == [page_no], "only that director's page changes"
    x0, top, x1, bottom = boxes[page_no]
    assert abs(rule["x0"] - 360.0) < TOL
    assert x0 >= 360.0 - 1 and x1 <= rule["x1"] + 1, "inside the right column's rule"
    assert bottom <= rule["y"] + 1, "the image sits on the rule, not below it"
    assert top > rule["y"] - 13.8 * 3, "and inside the three blank lines above it"


def test_a_director_who_did_not_sign_keeps_a_blank_line():
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    signed = resolution.render(CASE, ENTITY, entries, officers,
                               signatures={"P4": _stroke_png()})
    page_no, rule = _rules(base)[3]                   # INCOMING Four: row 2, right
    (box_page, (_x0, top, _x1, bottom)), = _ink_boxes(base, signed).items()
    assert box_page == page_no and bottom <= rule["y"] + 1


def test_a_director_who_is_leaving_signs_on_their_own_line():
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    signed = resolution.render(CASE, ENTITY, entries, officers,
                               signatures={"P3": _stroke_png()})
    page_no, rule = _rules(base)[2]                   # LEAVING Three: row 2, left
    (box_page, (x0, _top, _x1, bottom)), = _ink_boxes(base, signed).items()
    assert box_page == page_no and bottom <= rule["y"] + 1
    assert x0 >= 72.0 - 1 and abs(rule["x0"] - 72.0) < TOL


def test_a_signature_from_somebody_off_the_board_prints_nowhere():
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    stamped = resolution.render(CASE, ENTITY, entries, officers,
                                signatures={"NOBODY": _stroke_png()})
    assert _ink_boxes(base, stamped) == {}


def test_with_no_signatures_the_resolution_is_unchanged():
    """(reportlab stamps a creation time, so bytes differ run to run: compare
    what is drawn, as the spec's test 6 does — "the same text content".)"""
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    for signatures in (None, {}):
        again = resolution.render(CASE, ENTITY, entries, officers, signatures=signatures)
        assert _ink_boxes(base, again) == {} and _text(base) == _text(again)


def test_signing_adds_no_text_and_no_page():
    entries, officers = _two_directors_world()
    base = resolution.render(CASE, ENTITY, entries, officers)
    signed = resolution.render(CASE, ENTITY, entries, officers,
                               signatures={"P1": _stroke_png(), "P2": _stroke_png(),
                                           "P3": _stroke_png(), "P4": _stroke_png()})
    assert _text(base) == _text(signed)
    assert len(_pages(base)) == len(_pages(signed))
