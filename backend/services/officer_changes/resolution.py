"""The written resolution an ND2A goes with, to GSHK's current template.

Levi 2026-10-05: "I attached the sample written resolution for change of
director please build exactly to this written resolution sample ... in font
size, wordings and everything." The first sample is a Word document (US Letter);
its measurements, taken with PyMuPDF, are the constants below and are asserted by
`tests/officer_changes/test_resolution.py`. Neither it nor the template that
replaced it is committed: they name real companies and real directors.

2026-11-06 (Jacqueline Koh's UAT comments, relayed by Levi): GSHK sent a NEW
template, `Template - Written Resolutions.pdf`, and it is now the authority. It
supersedes the 2026-10-05 sample wherever the two differ, and four differences
are decisions rather than restyling:

  * THE SENTENCES. "IT IS RESOLVED that **<name>** shall resign as <role> from
    the company effective from the date hereof." replaces the R-1 wording ("of
    the company"), which was this module's own repair of a slip in the first
    sample; the client's template now says it its own way. The appointment
    sentence is the same words with the name in bold.
  * NO CLOSING SENTENCE. "Both changes shall also be filed and submitted to
    Companies Registry ..." is not in the new template, so `closing()` is gone.
  * THE BOARD THAT SIGNS IS THE BOARD BEFORE, PLUS THE NEW. Every director in
    office before the changes, including those ceasing, then every director
    appointed on this form. The old rule ("the board AFTER the changes", because
    the first sample's only signatory was the incoming director) is withdrawn:
    a director who is leaving is still a director when the resolution is
    passed, and the client asked for them by name. A director who has DIED
    keeps a line too (Jacqueline, UAT 2026-11-08, reversing this module's
    earlier "a line nobody can sign is not a signature line"): the
    administrator or executor of the estate signs it on the deceased's behalf,
    so it prints "Name:", "For and on behalf of the estate of", the director's
    name with "(deceased)", and "Administrator / Executor". "Name:" carries the
    administrator or executor typed on the cessation (`executor_name`,
    migration 062; Jacqueline, UAT 2026-11-10) and is blank without one. That
    person is not on record, so the line carries no person id and no
    e-signature is ever asked for or printed on it.
    Alternate directors sign too (Jacqueline, UAT 2026-11-09, PBI-70: "For
    the W/R, can we set for all the directors and alternative directors to
    sign?", then "Alternate director still not showing"): every alternate in
    office before the changes, after the directors, and every alternate
    appointed on this form, after the directors appointed. Their block ends
    "Alternate Director" where a director's ends "Director".
  * THE HEADER. Company name in English, then in Chinese on its own line when
    there is one, then "(Business License No. <BR number>)" (the template's
    wording, not "Business Registration No."), then "(the "Company")".

WHAT STAYS THE FIRST SAMPLE'S. The two heavy rules, the underlined headings
"Resignation of Director" / "Appointment of Director" (and now "... of
Alternate Director"), "Dated:" and the rule / "Name:" / "Director" blocks, now
two to a row at the template's own x positions. A body corporate director
prints "Name:", "For and on behalf of", its name, "Director". "Name:" carries
the individual who signs its consent when the body corporate is being APPOINTED
on this form; for an existing one nobody is on record and it stays blank. The type size and line
pitch are still the first sample's (12 pt, Word's 13.8), not the template's
11 pt; the brief was the words, the header and the signature block, and
re-pitching every baseline is a separate decision.

WHAT ELSE IS DECIDED HERE: a company secretary takes the same sentences with
"company secretary". An alternate director takes "... as alternate director to
<director> ...". A death is NOTED, not resolved. Two or more of one kind share
one heading, in the plural. `Dated:` prints the effective date when every
change shares one (two-digit day, `04 November 2026`: Levi 2026-11-06, "the date
format should always be DDMMYYYY"), and a line to fill in otherwise.

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
import math
import re
import sys
from datetime import date
from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from services.officer_change_form import stamp
from services.officer_changes import capacities
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
#: The template's two signature columns: the left block starts at the margin
#: and the right one at x 360 (read off `Template - Written Resolutions.pdf`).
SIGNATURE_COLUMNS = (LEFT, 360.0)
#: How wide a name may run before it wraps: up to the next column, and up to the
#: right margin.
_COLUMN_WIDTH = (SIGNATURE_COLUMNS[1] - LEFT - 12.0, RIGHT - SIGNATURE_COLUMNS[1])
#: The template's rule is 29 underscores.
SIGNATURE_RULE = "_" * 29
#: A drawn signature sits on its rule: at most this tall (the three blank lines
#: above a rule leave about 38pt), this far above the underscores.
SIGN_HEIGHT, SIGN_LIFT = 36.0, 1.5
TOP_MARGIN, BOTTOM_MARGIN = 72.0, 72.0

#: (ascent, descent) per line kind — see LINE HEIGHT in the module docstring.
_TIMES = (11.0, 2.8)
_CJK = (11.3, 5.0)

# -- the template's words -----------------------------------------------------------
# `**` marks the bold run: the template sets the officer's name in bold.

RESIGN = "IT IS RESOLVED that **{name}** shall resign as {role} from the company " \
         "effective from the date hereof."
APPOINT = "IT IS RESOLVED that the company shall appoint **{name}** as its new {role} " \
          "effective from the date hereof."
RESIGN_ALTERNATE = "IT IS RESOLVED that **{name}** shall resign as alternate director to " \
                   "{principal} from the company effective from the date hereof."
APPOINT_ALTERNATE = "IT IS RESOLVED that the company shall appoint **{name}** as alternate " \
                    "director to {principal} effective from the date hereof."
DEATH = "IT IS NOTED that **{name}** ceased to be {article} {role} of the company by " \
        "reason of death."
_ROLE = {"director": "director", "company_secretary": "company secretary",
         "alternate_director": "alternate director"}
_ROLE_TITLE = {"director": ("Director", "Directors"),
               "company_secretary": ("Company Secretary", "Company Secretaries"),
               "alternate_director": ("Alternate Director", "Alternate Directors")}
_ARTICLE = {"director": "a", "company_secretary": "the", "alternate_director": "an"}

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


# -- rich text: a sentence with one bold run ---------------------------------------

Segment = tuple[str, str]   # (text, latin face)


def _segments(text: str) -> list[Segment]:
    """`'a **b** c'` -> `[('a ', REGULAR), ('b', BOLD), (' c', REGULAR)]`."""
    out: list[Segment] = []
    for n, part in enumerate(text.split("**")):
        if part:
            out.append((part, BOLD if n % 2 else REGULAR))
    return out


def _rich_wrap(text: str, width: float) -> list[list[Segment]]:
    """Wrap a `**`-marked sentence word by word, keeping each word's weight. A
    line is a list of segments; the space after a word travels with it."""
    words: list[tuple[str, str]] = []
    for part, face in _segments(text):
        for token in re.findall(r"\S+|\s+", part):
            if token.isspace():
                words.append((" ", face))
            else:
                words.append((token, face))
    lines: list[list[Segment]] = [[]]
    used = 0.0
    pending = ""   # a space waiting to be printed before the next word
    for token, face in words:
        if token == " ":
            pending = " "
            continue
        w_token = _width(token, face)
        w_space = _width(pending, REGULAR) if pending else 0.0
        if lines[-1] and used + w_space + w_token > width:
            lines.append([])
            used, pending, w_space = 0.0, "", 0.0
        if lines[-1] and pending:
            lines[-1].append((pending, REGULAR))
        lines[-1].append((token, face))
        used += w_space + w_token
        pending = ""
    return lines


# -- content ------------------------------------------------------------------------

def file_name(case: dict) -> str:
    return f"Written-Resolution-{case.get('case_no') or case.get('id')}.pdf"


def _display(name, name_zh) -> str:
    name, zh = str(name or "").strip(), str(name_zh or "").strip()
    name, zh = name.replace("**", ""), zh.replace("**", "")
    if zh and zh != name:
        return f"{name} {zh}".strip()
    return name or zh


def _party(entry: dict) -> str:
    party = entry.get("party") or {}
    return _display(party.get("name"), party.get("name_zh")) or "the officer"


def _principal(entry: dict) -> str:
    """The director an alternate stands in for. Carried on the entry as
    `alternate_to_name` (ticket 03 resolves it); with none, a neutral phrase."""
    return _display(entry.get("alternate_to_name"), "") or "a director of the company"


def _sentence(entry: dict, capacity: str, death: bool) -> str:
    name = _party(entry)
    role = _ROLE[capacity]
    if death:
        text = DEATH.format(name=name, role=role, article=_ARTICLE[capacity])
        if capacity == "alternate_director" and entry.get("alternate_to_name"):
            text = text.replace(" of the company by", f" to {_principal(entry)} by")
        return text
    if capacity == "alternate_director":
        template = APPOINT_ALTERNATE if entry["kind"] == "appointment" else RESIGN_ALTERNATE
        return template.format(name=name, principal=_principal(entry))
    template = APPOINT if entry["kind"] == "appointment" else RESIGN
    return template.format(name=name, role=role)


def paragraphs(entries: list[dict]) -> list[tuple[str, list[str]]]:
    """`[(heading, [resolution, ...])]`, cessations before appointments, as the
    sample orders them; directors, then secretaries, then alternates. Each
    resolution is a `**`-marked sentence (the officer's name is bold)."""
    groups: dict[tuple, list[str]] = {}
    order = []
    for kind in ("cessation", "appointment"):
        for capacity in ("director", "company_secretary", "alternate_director"):
            for death in ((False, True) if kind == "cessation" else (False,)):
                order.append((kind, capacity, death))
    for entry in entries:
        capacity = entry.get("capacity")
        if capacity not in _ROLE or entry.get("kind") not in ("cessation", "appointment"):
            continue
        death = entry.get("kind") == "cessation" and entry.get("cessation_reason") == "D"
        groups.setdefault((entry["kind"], capacity, death), []).append(
            _sentence(entry, capacity, death))
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


def dated(entries: list[dict]) -> str | None:
    """The one effective date every change shares, as the template writes it:
    two-digit day, day first (`04 November 2026`)."""
    days = {_as_date(e.get("effective_date")) for e in entries}
    if len(days) != 1:
        return None
    day = days.pop()
    return f"{day:%d %B %Y}" if isinstance(day, date) else None


def _corporate(row: dict) -> bool:
    return (row.get("party_type") == "corporate"
            or (not row.get("person_id") and bool(row.get("corporate_entity_id"))))


def _signers(entries: list[dict], officers: list[dict]) -> list[dict]:
    """Everyone who signs, in order, de-duplicated by party: every director in
    office BEFORE the changes (those ceasing included), then every alternate
    director in office before them, then every director appointed on this
    form, then every alternate appointed on it.
    `{name, person_id, corporate, deceased, title}` each.

    This is the ONE statement of who signs, and the views below read it (so an
    alternate with a line is also asked for a drawn signature, and the
    multi-signer round includes them). A director who has died keeps their
    line, for the administrator or executor of the estate, and that line
    carries NO person id: the deceased cannot be asked to sign and the executor
    is not on record, so nobody is sent a link for it and no drawn signature
    can land on it."""
    # officer -> the administrator / executor named on their cessation ("" when
    # none is), for every director ceasing by death on this form.
    dead = {e["officer_id"]: _executor(e) for e in entries
            if e.get("kind") == "cessation" and e.get("cessation_reason") == "D"
            and e.get("officer_id")}
    rows: list[dict] = []
    for capacity in capacities.DIRECTORS:
        for o in officers:
            if o.get("role") != capacity:
                continue
            deceased = o.get("officer_id") in dead or bool(o.get("date_of_death"))
            rows.append({"name": _display(o.get("name"), o.get("name_zh")),
                         "person_id": None if deceased else o.get("person_id"),
                         "key": o.get("person_id") or o.get("corporate_entity_id"),
                         "corporate": _corporate(o), "deceased": deceased,
                         "title": capacities.LABEL[capacity],
                         "signs_for": dead.get(o.get("officer_id")) or ""})
    # Once the changes are written to the profile (`apply`), a director who
    # ceased is no longer among `officers`; their line comes from the cessation
    # entry instead, so a filed case re-renders the resolution they signed
    # (review S4) rather than one without them.
    listed = {o.get("officer_id") for o in officers}
    for capacity in capacities.DIRECTORS:
        for e in entries:
            if (e.get("kind") == "cessation" and e.get("capacity") == capacity
                    and e.get("officer_id") not in listed
                    and (e.get("party") or {}).get("name")):
                deceased = e.get("cessation_reason") == "D"
                rows.append({"name": _party(e),
                             "person_id": None if deceased else e.get("person_id"),
                             "key": e.get("person_id") or e.get("corporate_entity_id"),
                             "corporate": _corporate(e), "deceased": deceased,
                             "title": capacities.LABEL[capacity],
                             "signs_for": _executor(e) if deceased else ""})
    for capacity in capacities.DIRECTORS:
        for e in entries:
            if e.get("kind") != "appointment" or e.get("capacity") != capacity:
                continue
            corporate = _corporate(e)
            # A body corporate being appointed names, on its appointment, the
            # individual who signs its consent ("Consent signed by"); that is
            # who signs for it here too, so the name is printed rather than
            # left blank (UAT 2026-11-08, PBI-52). An existing corporate
            # director has nobody on record, and keeps a blank "Name:".
            rows.append({"name": _party(e), "person_id": e.get("person_id"),
                         "key": e.get("person_id") or e.get("corporate_entity_id"),
                         "corporate": corporate, "deceased": False,
                         "title": capacities.LABEL[capacity],
                         "signs_for": (str(e.get("consent_person_name") or "").strip()
                                       if corporate else "")})
    seen, out = set(), []
    for row in rows:
        # A person is one line even when a raw entry (which carries no display
        # name) stands in for them, so the identity is the party id when there
        # is one, and the name otherwise.
        key = row["key"] or row["name"]
        if row["name"] and key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _executor(entry: dict) -> str:
    """The administrator / executor named on a death's cessation, or ""."""
    return " ".join(str(entry.get("executor_name") or "").split())


def signatories(entries: list[dict], officers: list[dict]) -> list[str]:
    """The names on the signature lines, in order."""
    return [row["name"] for row in _signers(entries, officers)]


def signatory_people(entries: list[dict], officers: list[dict]) -> list[tuple[str, str | None]]:
    """`[(name, person_id)]`: the same signature lines as `signatories`, in the
    same order, each with the person it belongs to (None for a line the portal
    cannot attribute: a body corporate, or a deceased director's estate). `signatories` keeps returning
    names alone because its callers and tests expect `list[str]`."""
    return [(row["name"], row["person_id"]) for row in _signers(entries, officers)]


def _rule_for(block: list[str]) -> str:
    """The signature rule over one block: the template's 29 underscores, or as
    many as it takes to reach the end of the longest line under it, whichever
    is longer (Jacqueline, UAT 2026-11-09: "make the line the same length as
    the name" -- a long name with Chinese ran past a fixed rule). The lines are
    already wrapped to the column, so the rule never crosses into the next."""
    longest = max((_width(line, REGULAR) for line in block), default=0.0)
    underscore = _width("_", REGULAR)
    return "_" * max(len(SIGNATURE_RULE), math.ceil(longest / underscore))


def _block_lines(row: dict, width: float) -> list[str]:
    """The text lines under one signature rule."""
    title = row.get("title") or "Director"
    signer = row.get("signs_for")
    named = _wrap(f"Name: {signer}", REGULAR, width) if signer else ["Name:"]
    if row.get("deceased"):
        # "Name:" carries the administrator / executor when the cessation
        # names one (UAT 2026-11-10, PBI-59), and is left to the pen otherwise.
        lines = [*named, "For and on behalf of the estate of",
                 *_wrap(f"{row['name']} (deceased)", REGULAR, width),
                 "Administrator / Executor"]
    elif row["corporate"]:
        lines = [*named, "For and on behalf of", *_wrap(row["name"], REGULAR, width), title]
    else:
        lines = [*_wrap(f"Name: {row['name']}", REGULAR, width), title]
    return lines


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

    def cells(self, items: list[tuple[str, float]]) -> None:
        """One baseline, several columns: `[(text, x)]`."""
        self._advance(_CJK if any(_is_cjk_line(t, REGULAR) for t, _ in items) else _TIMES)
        self.fresh = False
        for text, x in items:
            _draw(self.pdf, text, x, self.y, REGULAR)

    def paragraph(self, text: str) -> None:
        for line in _rich_wrap(text, RIGHT - LEFT):
            self._advance(_CJK if any(_is_cjk_line(t, f) for t, f in line) else _TIMES)
            self.fresh = False
            x = LEFT
            for chunk, face in line:
                _draw(self.pdf, chunk, x, self.y, face)
                x += _width(chunk, face)

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


def _header(entity: dict) -> list[str]:
    """The template's header lines, bold and centred between the heavy rules."""
    english = str(entity.get("company_name") or "").strip()
    chinese = str(entity.get("company_name_zh") or "").strip()
    lines = ["WRITTEN RESOLUTIONS OF"]
    if english:
        lines += _wrap(english, BOLD, RIGHT - LEFT)
    if chinese and chinese != english:
        lines += _wrap(chinese, BOLD, RIGHT - LEFT)
    if not english and not chinese:
        lines.append("The Company")
    if str(entity.get("br_number") or "").strip():
        lines.append(f"(Business License No. {str(entity['br_number']).strip()})")
    lines.append("(the “Company”)")
    return lines


def render(case: dict, entity: dict, entries: list[dict], officers: list[dict],
           signatures: dict[str, bytes] | None = None) -> bytes:
    """The PDF.

    `signatures` is `{person_id: PNG}`, OFF by default: only a caller rendering a
    resolution the client has CONFIRMED passes it (`signatures.images_for`), and
    the send never does, so a draft is unsigned by definition. Each director on
    a signature line who has a picture gets it printed on their rule."""
    for name in (REGULAR, BOLD, CJK):
        _font(name)
    company = (str(entity.get("company_name") or "").strip()
               or str(entity.get("company_name_zh") or "").strip() or "The Company")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))
    pdf.setTitle(f"Written Resolutions of {company}")
    pdf.setFillColorRGB(0, 0, 0)

    _rule(pdf, RULE1_TOP)
    baseline = HEADER_FIRST
    header = _header(entity)
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
        # The 2026-11-06 template sets the first sentence directly under its
        # heading; a second sentence of the same kind is set off by a blank line.
        for n, text in enumerate(texts):
            if n:
                page.blank()
            page.paragraph(text)
        page.blank()
        page.blank()
    page.line(f"Dated: {dated(entries) or '_' * 20}")

    signers = _signers(entries, officers)
    for start in range(0, len(signers), 2):
        row = signers[start:start + 2]
        blocks = [_block_lines(s, _COLUMN_WIDTH[n]) for n, s in enumerate(row)]
        height = 1 + max(len(b) for b in blocks)        # the rule, then the block
        spacing = 4 if start == 0 else 3
        # A row is its spacing plus its rule and lines, and is never split
        # across pages (review finding 4).
        if not page.room_for(spacing + height):
            pdf.showPage()
            page.y, page.descent, page.fresh = TOP_MARGIN, 0.0, True
        for _ in range(spacing):
            page.blank()
        page.cells([(_rule_for(b), SIGNATURE_COLUMNS[n]) for n, b in enumerate(blocks)])
        rule_y = page.y
        for n, s in enumerate(row):
            if signatures and s["person_id"] and s["person_id"] in signatures:
                _sign(pdf, signatures[s["person_id"]], rule_y, SIGNATURE_COLUMNS[n])
        for i in range(height - 1):
            page.cells([(b[i], SIGNATURE_COLUMNS[n]) for n, b in enumerate(blocks)
                        if i < len(b)])
    pdf.save()
    return buffer.getvalue()


def _sign(pdf: canvas.Canvas, png: bytes, rule_baseline: float, x: float) -> None:
    """Draw one director's picture ON their rule: left edge at the rule's,
    bottom just above the underscores' baseline, scaled to fit the room the
    blank lines above the rule leave (never beyond 1 pixel : 1 point). A picture
    that will not draw is left off; the rule stays for a pen."""
    try:
        img = stamp.prepared(png)
        w, h = stamp.fit(img.width, img.height, _width(SIGNATURE_RULE, REGULAR), SIGN_HEIGHT)
        pdf.drawImage(ImageReader(img), x, PAGE_H - rule_baseline + SIGN_LIFT,
                      width=w, height=h, mask="auto")
    except Exception as exc:  # noqa: BLE001
        print(f"[resolution] a signature could not be drawn: {exc}", file=sys.stderr)
