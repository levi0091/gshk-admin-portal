"""The written resolution an ND2A goes with — GSHK's own sample, exactly.

Levi 2026-10-05: "build exactly to this written resolution sample ... in font
size, wordings and everything." The sample (`Sample Written Resolution - Change
of Director.pdf`, Word, US Letter) is not committed — it names a real company
and real directors — so its measurements are transcribed here, taken with
PyMuPDF off the file itself:

  rules       1.44 pt black, x 70.58-541.53, top edges at y 86.42 and 179.54
  header      Times New Roman Bold 12, centred, baselines 112.9 128.8 144.6 160.5
  heading     Bold 12, underlined; first at baseline 206.1, second at 291.4
  body        Regular 12 at x 72; 234.0 / 250.0 and 319.4 / 335.2
  closing     376.6 / 390.4
  Dated       473.2
  signature   x 77.4: underscores 542.2, Name 556.4, Director 572.3

The sample's case is reproduced below: one director resigning, one appointed,
both on 20 March 2026, the newcomer the only director left to sign.
"""
import pymupdf
import pytest

from services.officer_changes import resolution

TOL = 0.6

CASE = {"id": "K1", "case_no": "ND2A-2026-0007", "form_code": "Nd2a"}
ENTITY = {"company_name": "ZenithStream Limited", "br_number": "75092262"}
OFFICERS = [
    {"officer_id": "O1", "role": "director", "name": "PIK YI REBECCA LAW", "name_zh": "羅碧儀"},
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
                    ("(Business Registration No. 75092262)", 144.6),
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
                      ("Both changes shall also be filed", 376.6),
                      ("Dated:", 473.2),
                      ("____", 542.2), ("Name: Aldo KRIEL", 556.4), ("Director", 572.3)):
        line = _line(sample_page, starts)
        assert abs(line["y"] - y) < TOL, (starts, line["y"], y)
    # Second lines of the two-line paragraphs (Word's taller line after Chinese).
    ys = [r["y"] for r in _lines(sample_page)]
    for y in (250.0, 335.2, 390.4):
        assert any(abs(v - y) < TOL for v in ys), y


def test_body_is_times_12_regular_and_headings_bold_underlined(sample_page):
    body = _line(sample_page, "Both changes shall also be filed")
    assert body["size"] == 12 and all("Bold" not in f for f in body["fonts"])
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


def test_signature_block_is_indented_as_the_sample(sample_page):
    for starts in ("____", "Name: Aldo KRIEL", "Director"):
        assert abs(_line(sample_page, starts)["x0"] - 77.4) < TOL, starts


def test_the_sample_wording():
    out = _text(resolution.render(CASE, ENTITY, SAMPLE, OFFICERS))
    assert ("IT IS RESOLVED that PIK YI REBECCA LAW 羅碧儀 shall resign as director of the "
            "company effective from the date hereof.") in out
    assert ("IT IS RESOLVED that the company shall appoint Aldo KRIEL 歐立德 as its new "
            "director effective from the date hereof.") in out
    assert ("Both changes shall also be filed and submitted to Companies Registry via its "
            "electronic services signed under director’s capacity.") in out
    assert "Dated: 20 March 2026" in out
    assert "Name: Aldo KRIEL 歐立德 Director" in out
    # The outgoing director does not sign: the board after the change does.
    assert "Name: PIK YI REBECCA LAW" not in out


def test_one_change_says_this_change():
    out = _text(resolution.render(CASE, ENTITY, [APPOINT], OFFICERS))
    assert "This change shall also be filed and submitted to Companies Registry" in out
    assert "Both changes" not in out


def test_three_changes_say_all_changes():
    second = {**APPOINT, "id": "N3", "party": {"name": "HO New"}}
    out = _text(resolution.render(CASE, ENTITY, SAMPLE + [second], OFFICERS))
    assert "All changes shall also be filed" in out
    assert "Appointment of Directors" in out


def test_a_secretary_is_worded_as_a_secretary():
    entries = [{"id": "N1", "kind": "cessation", "capacity": "company_secretary",
                "officer_id": "O3", "cessation_reason": "R", "effective_date": "2026-03-20",
                "party": {"name": "Get Started HK Limited"}},
               {"id": "N2", "kind": "appointment", "capacity": "company_secretary",
                "effective_date": "2026-03-20", "party": {"name": "Island Secretaries Limited"}}]
    out = _text(resolution.render(CASE, ENTITY, entries, OFFICERS))
    assert "Resignation of Company Secretary" in out and "Appointment of Company Secretary" in out
    assert ("IT IS RESOLVED that Get Started HK Limited shall resign as company secretary of "
            "the company effective from the date hereof.") in out
    assert ("IT IS RESOLVED that the company shall appoint Island Secretaries Limited as its "
            "new company secretary effective from the date hereof.") in out


def test_a_death_is_noted_not_resolved():
    dead = {**RESIGN, "cessation_reason": "D"}
    out = _text(resolution.render(CASE, ENTITY, [dead, APPOINT], OFFICERS))
    assert "Cessation of Director" in out
    assert ("IT IS NOTED that PIK YI REBECCA LAW 羅碧儀 ceased to be a director of the "
            "company by reason of death.") in out


def test_dated_is_left_blank_when_the_dates_differ_or_are_missing():
    later = {**APPOINT, "effective_date": "2026-03-21"}
    assert "Dated: ____" in _text(resolution.render(CASE, ENTITY, [RESIGN, later], OFFICERS))
    undated = {**APPOINT, "effective_date": None}
    assert "Dated: ____" in _text(resolution.render(CASE, ENTITY, [undated], OFFICERS))


def test_every_director_after_the_change_signs():
    officers = OFFICERS + [{"officer_id": "O4", "role": "director", "name": "CHAN Tai Man"}]
    out = _text(resolution.render(CASE, ENTITY, SAMPLE, officers))
    assert "Name: CHAN Tai Man Director" in out and "Name: Aldo KRIEL 歐立德 Director" in out


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


def test_signatories_are_the_board_after_the_changes():
    assert resolution.signatories(SAMPLE, OFFICERS) == ["Aldo KRIEL 歐立德"]


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
