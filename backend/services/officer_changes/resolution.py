"""The written resolution an ND2A goes with — GSHK's own sample, exactly.

Levi 2026-10-05: "I attached the sample written resolution for change of
director please build exactly to this written resolution sample ... in font
size, wordings and everything." The sample is a Word document (US Letter); its
measurements, taken with PyMuPDF, are the constants below and are asserted by
`tests/officer_changes/test_resolution.py`. The sample itself is not committed:
it names a real company and real directors.

WHAT IS THE SAMPLE'S, VERBATIM. The header between two heavy rules; the
underlined headings "Resignation of Director" / "Appointment of Director"; "IT
IS RESOLVED that ... as its new director effective from the date hereof."; the
closing "Both changes shall also be filed and submitted to Companies Registry
via its electronic services signed under director's capacity."; "Dated:"; one
signature line per director with "Name:" and "Director" beneath.

WHAT IS DECIDED HERE (spec 2026-10-05 §9, R-1 and R-2):

  * The sample's resignation sentence reads "shall resign as director effective
    from the company effective from the date hereof" — an evident slip. This
    prints "... as director of the company effective from the date hereof."
    (`RESIGN`, one constant.)
  * A company secretary takes the same sentences with "company secretary". A
    death is NOTED, not resolved. Two or more of one kind share one heading,
    in the plural. The closing sentence says "This change" / "Both changes" /
    "All changes". `Dated:` prints the effective date when every change shares
    one, and a line to fill in otherwise. Every director in office AFTER the
    changes signs — the sample's signatory is the incoming director, the only
    one left.

TYPE. Times New Roman 12 is Tinos 12, metric-identical (see
`nar1_form/fonts/README.md`). The sample sets Chinese names in DengXian, which
cannot be shipped; Noto Sans TC Regular is the nearest free face. A character
neither carries falls back to Noto Serif SC, as the NAR1 renderer does.

LINE HEIGHT is Word's: 13.8 pt between Times lines, and a line carrying Chinese
sits 0.3 pt lower and pushes the next 2.2 pt further down (DengXian's taller
ascent and descent) — which is why the sample's second lines are at +16.0.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from services.officer_changes.deadlines import _as_date

# -- the sample's geometry (points; y measured DOWN from the top edge) -----------

PAGE_W, PAGE_H = 612.0, 792.0
LEFT, RIGHT = 72.0, 540.0
CENTRE = (LEFT + RIGHT) / 2
SIZE = 12.0
RULE_X0, RULE_X1, RULE_THICK = 70.58, 541.53, 1.44
RULE1_TOP = 86.42
HEADER_FIRST, HEADER_PITCH = 112.9, 15.87
RULE2_AFTER_HEADER = 179.54 - 160.5      # last header baseline -> second rule
FIRST_FLOW_AFTER_RULE2 = 192.3 - 179.54  # second rule -> first (blank) body line
UNDERLINE_BELOW, UNDERLINE_THICK = 1.28, 1.2
SIGNATURE_X = 77.4
SIGNATURE_RULE = "_" * 36
TOP_MARGIN, BOTTOM_MARGIN = 72.0, 72.0

#: (ascent, descent) per line kind — see LINE HEIGHT in the module docstring.
_TIMES = (11.0, 2.8)
_CJK = (11.3, 5.0)

# -- the sample's words -------------------------------------------------------------

RESIGN = "IT IS RESOLVED that {name} shall resign as {role} of the company effective " \
         "from the date hereof."
APPOINT = "IT IS RESOLVED that the company shall appoint {name} as its new {role} " \
          "effective from the date hereof."
DEATH = "IT IS NOTED that {name} ceased to be {article} {role} of the company by " \
        "reason of death."
CLOSING = "{count} shall also be filed and submitted to Companies Registry via its " \
          "electronic services signed under director’s capacity."
_COUNT = {1: "This change", 2: "Both changes"}
_ROLE = {"director": "director", "company_secretary": "company secretary"}
_ROLE_TITLE = {"director": ("Director", "Directors"),
               "company_secretary": ("Company Secretary", "Company Secretaries")}

# -- fonts ----------------------------------------------------------------------------

_FONT_DIR = Path(__file__).resolve().parents[1] / "nar1_form" / "fonts"
REGULAR, BOLD, CJK, CJK_FALLBACK = ("GFD-Tinos", "GFD-Tinos-Bold", "GFD-NotoSansTC",
                                    "GFD-NotoSerifSC-Bold")
_FILES = {REGULAR: "Tinos-Regular.ttf", BOLD: "Tinos-Bold.ttf",
          CJK: "NotoSansTC-Regular.ttf", CJK_FALLBACK: "NotoSerifSC-Bold.ttf"}


def _font(name: str):
    try:
        return pdfmetrics.getFont(name)
    except KeyError:
        pdfmetrics.registerFont(TTFont(name, str(_FONT_DIR / _FILES[name])))
        return pdfmetrics.getFont(name)


def _has(name: str, char: str) -> bool:
    return ord(char) in _font(name).face.charToGlyph


def _face_for(char: str, latin: str) -> str:
    if char == " " or _has(latin, char):
        return latin
    if _has(CJK, char):
        return CJK
    # Loaded only when needed: it is a 15 MB file.
    if _has(CJK_FALLBACK, char):
        return CJK_FALLBACK
    return latin


def _runs(text: str, latin: str) -> list[tuple[str, str]]:
    runs: list[list[str]] = []
    for char in text:
        face = _face_for(char, latin)
        if runs and runs[-1][0] == face:
            runs[-1][1] += char
        else:
            runs.append([face, char])
    return [(f, t) for f, t in runs]


def _width(text: str, latin: str) -> float:
    return sum(pdfmetrics.stringWidth(t, f, SIZE) for f, t in _runs(text, latin))


def _is_cjk_line(text: str, latin: str) -> bool:
    return any(f != latin for f, _ in _runs(text, latin))


def _wrap(text: str, latin: str, width: float) -> list[str]:
    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and _width(candidate, latin) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


# -- content ------------------------------------------------------------------------

def file_name(case: dict) -> str:
    return f"Written-Resolution-{case.get('case_no') or case.get('id')}.pdf"


def _display(name, name_zh) -> str:
    name, zh = str(name or "").strip(), str(name_zh or "").strip()
    if zh and zh != name:
        return f"{name} {zh}".strip()
    return name or zh


def _party(entry: dict) -> str:
    party = entry.get("party") or {}
    return _display(party.get("name"), party.get("name_zh")) or "the officer"


def paragraphs(entries: list[dict]) -> list[tuple[str, list[str]]]:
    """`[(heading, [resolution, ...])]`, cessations before appointments, as the
    sample orders them; directors before secretaries."""
    groups: dict[tuple, list[str]] = {}
    order = []
    for kind in ("cessation", "appointment"):
        for capacity in ("director", "company_secretary"):
            for death in ((False, True) if kind == "cessation" else (False,)):
                order.append((kind, capacity, death))
    for entry in entries:
        capacity = entry.get("capacity")
        if capacity not in _ROLE or entry.get("kind") not in ("cessation", "appointment"):
            continue
        death = entry.get("kind") == "cessation" and entry.get("cessation_reason") == "D"
        role = _ROLE[capacity]
        if entry["kind"] == "appointment":
            text = APPOINT.format(name=_party(entry), role=role)
        elif death:
            text = DEATH.format(name=_party(entry), role=role,
                                article="a" if capacity == "director" else "the")
        else:
            text = RESIGN.format(name=_party(entry), role=role)
        groups.setdefault((entry["kind"], capacity, death), []).append(text)
    out = []
    for key in order:
        texts = groups.get(key)
        if not texts:
            continue
        kind, capacity, death = key
        title = _ROLE_TITLE[capacity][0 if len(texts) == 1 else 1]
        verb = "Appointment" if kind == "appointment" else ("Cessation" if death
                                                             else "Resignation")
        out.append((f"{verb} of {title}", texts))
    return out


def closing(entries: list[dict]) -> str:
    count = sum(len(texts) for _, texts in paragraphs(entries))
    return CLOSING.format(count=_COUNT.get(count, "All changes"))


def dated(entries: list[dict]) -> str | None:
    """The one effective date every change shares, as the sample writes it."""
    days = {_as_date(e.get("effective_date")) for e in entries}
    if len(days) != 1:
        return None
    day = days.pop()
    return f"{day.day} {day:%B %Y}" if isinstance(day, date) else None


def signatories(entries: list[dict], officers: list[dict]) -> list[str]:
    """Every director in office AFTER the changes: those staying, then those
    appointed. With nobody left, the directors in office before."""
    leaving = {e.get("officer_id") for e in entries
               if e.get("kind") == "cessation" and e.get("officer_id")}
    directors = [o for o in officers if o.get("role") == "director"]
    names = [_display(o.get("name"), o.get("name_zh")) for o in directors
             if o.get("officer_id") not in leaving]
    names += [_party(e) for e in entries
              if e.get("kind") == "appointment" and e.get("capacity") == "director"]
    if not names:
        names = [_display(o.get("name"), o.get("name_zh")) for o in directors]
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


# -- layout ---------------------------------------------------------------------------

class _Page:
    """A cursor over the sample's flow: `y` is the last baseline drawn."""

    def __init__(self, pdf: canvas.Canvas):
        self.pdf = pdf
        self.y = 0.0
        self.descent = _TIMES[1]
        self.fresh = False

    def _advance(self, metrics) -> None:
        ascent, descent = metrics
        if self.y + self.descent + ascent + descent > PAGE_H - BOTTOM_MARGIN:
            self.pdf.showPage()
            self.y, self.descent, self.fresh = TOP_MARGIN, 0.0, True
        self.y += self.descent + ascent
        self.descent = descent

    def blank(self) -> None:
        if self.fresh:  # a new page starts with words, not with spacing
            return
        self._advance(_TIMES)

    def line(self, text: str, *, latin: str = REGULAR, x: float = LEFT,
             underline: bool = False) -> None:
        self._advance(_CJK if _is_cjk_line(text, latin) else _TIMES)
        self.fresh = False
        _draw(self.pdf, text, x, self.y, latin)
        if underline:
            width = _width(text.rstrip(), latin)
            self.pdf.rect(x, PAGE_H - (self.y + UNDERLINE_BELOW) - UNDERLINE_THICK, width,
                          UNDERLINE_THICK, stroke=0, fill=1)

    def paragraph(self, text: str, *, latin: str = REGULAR) -> None:
        for line in _wrap(text, latin, RIGHT - LEFT):
            self.line(line, latin=latin)

    def room_for(self, lines: int) -> bool:
        return self.y + self.descent + lines * sum(_CJK) <= PAGE_H - BOTTOM_MARGIN


def _draw(pdf: canvas.Canvas, text: str, x: float, baseline: float, latin: str) -> None:
    for face, chunk in _runs(text, latin):
        pdf.setFont(face, SIZE)
        pdf.drawString(x, PAGE_H - baseline, chunk)
        x += pdfmetrics.stringWidth(chunk, face, SIZE)


def _rule(pdf: canvas.Canvas, top: float) -> None:
    pdf.rect(RULE_X0, PAGE_H - top - RULE_THICK, RULE_X1 - RULE_X0, RULE_THICK,
             stroke=0, fill=1)


def render(case: dict, entity: dict, entries: list[dict], officers: list[dict]) -> bytes:
    """The PDF."""
    for name in (REGULAR, BOLD, CJK):
        _font(name)
    company = (str(entity.get("company_name") or "").strip()
               or str(entity.get("company_name_zh") or "").strip() or "The Company")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    pdf.setTitle(f"Written Resolutions of {company}")
    pdf.setFillColorRGB(0, 0, 0)

    header = ["WRITTEN RESOLUTIONS OF", *_wrap(company, BOLD, RIGHT - LEFT)]
    if str(entity.get("br_number") or "").strip():
        header.append(f"(Business Registration No. {str(entity['br_number']).strip()})")
    header.append("(the “Company”)")
    _rule(pdf, RULE1_TOP)
    baseline = HEADER_FIRST
    for text in header:
        _draw(pdf, text, CENTRE - _width(text, BOLD) / 2, baseline, BOLD)
        baseline += HEADER_PITCH
    last = baseline - HEADER_PITCH
    rule2 = last + RULE2_AFTER_HEADER
    _rule(pdf, rule2)

    page = _Page(pdf)
    page.y = rule2 + FIRST_FLOW_AFTER_RULE2 - _TIMES[0] - _TIMES[1]
    page.blank()
    for heading, texts in paragraphs(entries):
        page.line(heading, latin=BOLD, underline=True)
        for n, text in enumerate(texts):
            page.blank()
            page.paragraph(text)
        page.blank()
        page.blank()
    page.paragraph(closing(entries))
    for _ in range(5):
        page.blank()
    page.line(f"Dated: {dated(entries) or '_' * 20}")
    for n, name in enumerate(signatories(entries, officers)):
        if not page.room_for(4 if n == 0 else 7):
            pdf.showPage()
            page.y, page.descent, page.fresh = TOP_MARGIN, 0.0, True
        for _ in range(4 if n == 0 else 3):
            page.blank()
        page.line(SIGNATURE_RULE, x=SIGNATURE_X)
        page.line(f"Name: {name}", x=SIGNATURE_X)
        page.line("Director", x=SIGNATURE_X)
    pdf.save()
    return buffer.getvalue()
