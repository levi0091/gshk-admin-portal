"""The baked text layer that makes the generated NAR1 render identically
everywhere.

WHY THIS EXISTS. The values used to be AcroForm field values and nothing else.
Every one of them carried an appearance stream pointing at `/PMingLiU` -- a
Traditional Chinese face the template does not embed -- under
`NeedAppearances=true`, which tells conforming viewers to throw those streams
away and regenerate from `/DA`. Acrobat and Outlook obey; Chrome's pdfium
largely renders the existing stream. Same bytes, two documents, which is
exactly what the client reported.

So the values are drawn as a real page layer in fonts we embed, the widgets
are hidden so nothing paints over it, and NeedAppearances is cleared. `/V` is
still written -- the data stays machine-readable and the existing suite still
asserts on it -- but no viewer is asked to interpret it any more.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: reportlab's names for the faces. Prefixed so they cannot collide with a
#: font another part of the app registers in the same process.
FONT_LATIN_BOLD = "NAR1-Bold"
FONT_LATIN = "NAR1-Regular"
FONT_CJK = "NAR1-CJK"
FONT_CJK_SC = "NAR1-CJK-SC"

_FILES = {
    FONT_LATIN_BOLD: "Tinos-Bold.ttf",
    FONT_LATIN: "Tinos-Regular.ttf",
    FONT_CJK: "NotoSerifTC-Bold.ttf",
    FONT_CJK_SC: "NotoSerifSC-Bold.ttf",
}

#: CJK faces in preference order. Hong Kong's register is TRADITIONAL, so the
#: TC face is tried first and the SC face only catches what it cannot draw --
#: otherwise a company name both faces cover would render in Simplified
#: shapes on a Hong Kong statutory return.
#:
#: SC is here because TC alone is not enough for this book. Measured on DEV:
#: 2 of 473 `persons.full_name_zh` and 1 of 119 `entities.company_name_zh`
#: rows carry characters Noto Serif TC has no glyph for -- among them
#: U+6768 杨, the simplified form of a top-ten Hong Kong surname. Mainland
#: directors of Hong Kong companies are ordinary, and their names arrive in
#: Simplified.
_CJK_FACES = (FONT_CJK, FONT_CJK_SC)

_registered = False

#: font name -> the set of Unicode codepoints its cmap can actually draw.
#: Populated once by `register_fonts()`, from `TTFont.face.charToGlyph` --
#: reading a TTF's cmap is not free, and a render checks coverage on every
#: character of every field, so this is built once per process rather than
#: once per character per render.
_CMAPS: dict[str, frozenset] = {}


class AppearanceError(RuntimeError):
    """The text layer could not be drawn."""


def _codepoint_hex(v: int) -> str:
    """A ToUnicode CMap operand for codepoint `v`, per the PDF spec.

    Anything above the Basic Multilingual Plane -- which is every CJK
    Extension B character routing now sends to the CJK face -- must be
    expressed as a UTF-16BE surrogate pair, two 4-digit halves.
    """
    if v <= 0xFFFF:
        return "%04X" % v
    v -= 0x10000
    return "%04X%04X" % (0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF))


def _patched_make_to_unicode_cmap(fontname, subset):
    """Corrects `reportlab.pdfbase.ttfonts.makeToUnicodeCMap`.

    The stock function writes `"<%04X>" % v` for every codepoint in the
    font's subset. For anything above U+FFFF that produces a 5-or-more-digit
    hex string, which is not valid ToUnicode CMap syntax -- pypdf's reader
    logs "Got invalid hex string: Odd-length string" and returns nothing
    for that glyph. The GLYPH still draws correctly either way (drawing goes
    through the font's own cmap, not this one) but text extraction, search
    and copy-paste for a CJK Extension B name silently break. Monkeypatched
    at registration time rather than forked: this is reportlab's own
    upstream defect, not something this module owns, and the one-line
    change is worth carrying as a patch rather than a vendored copy of the
    whole function.
    """
    cmap = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        "<< /Registry (%s)" % fontname,
        "/Ordering (%s)" % fontname,
        "/Supplement 0",
        ">> def",
        "/CMapName /%s def" % fontname,
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<00> <%02X>" % (len(subset) - 1),
        "endcodespacerange",
        "%d beginbfchar" % len(subset)
        ] + ["<%02X> <%s>" % (i, _codepoint_hex(v))
             for i, v in enumerate(subset)] + [
        "endbfchar",
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end"
        ]
    return "\n".join(cmap)


def register_fonts() -> None:
    """Register the three faces with reportlab. Idempotent and cheap after
    the first call, which matters because it runs on every render."""
    global _registered
    if _registered:
        return
    import reportlab.pdfbase.ttfonts as _ttfonts
    _ttfonts.makeToUnicodeCMap = _patched_make_to_unicode_cmap
    for name, filename in _FILES.items():
        path = FONT_DIR / filename
        if not path.exists():
            raise AppearanceError(
                f"the NAR1 font {filename} is missing from {FONT_DIR}. It is a "
                f"runtime asset, not documentation -- see fonts/README.md"
            )
        pdfmetrics.registerFont(TTFont(name, str(path)))
        _CMAPS[name] = frozenset(pdfmetrics.getFont(name).face.charToGlyph.keys())
    _registered = True


def _is_cjk(char: str) -> bool:
    """CJK ideographs, radicals, and the fullwidth forms that travel with
    them. Deliberately NOT all of 'not ASCII': accented Latin belongs in the
    Latin face, and routing it to the CJK one would change its shape."""
    code = ord(char)
    return (0x2E80 <= code <= 0x9FFF      # radicals through CJK Unified
                                          # (includes Extension A, U+3400-4DBF)
            or 0xF900 <= code <= 0xFAFF   # compatibility ideographs
            or 0xFF00 <= code <= 0xFFEF   # fullwidth / halfwidth forms
            # Extension B through the Compatibility Ideographs Supplement.
            # Without this a name like a director's, carrying a character
            # only encoded here, was routed to Tinos -- which has 0 glyphs
            # in this range -- rather than to the CJK face that may have one.
            # CR's own template embeds PMingLiU-ExtB, which is direct
            # evidence CR expects these characters on a filed NAR1.
            or 0x20000 <= code <= 0x2FA1F)


def _uncoverable(font: str, text: str) -> list[str]:
    """Characters in `text` the registered `font` has no glyph for, in the
    order they first appear and without repeats."""
    cmap = _CMAPS.get(font)
    if cmap is None:
        # register_fonts() has not run yet on this process -- callers all
        # route through `bake()`, which registers first, but this guards
        # against a future direct caller silently treating "not yet
        # registered" as "nothing is coverable".
        register_fonts()
        cmap = _CMAPS.get(font, frozenset())
    return [char for char in dict.fromkeys(text) if ord(char) not in cmap]


def _cjk_face_for(char: str) -> str:
    """The first CJK face that can actually draw `char`.

    Falls through to the LAST face when none covers it, so the character still
    reaches the coverage guard in `draw_value` and is refused there by name
    rather than silently disappearing here.
    """
    for face in _CJK_FACES:
        if ord(char) in _CMAPS.get(face, frozenset()):
            return face
    return _CJK_FACES[-1]


def split_runs(text: str, *, bold: bool = True) -> list[tuple[str, str]]:
    """Split `text` into consecutive (font name, chunk) runs.

    Per character, because a Hong Kong address is routinely half English and
    half Chinese and a single font for the whole value would drop one half.
    """
    latin = FONT_LATIN_BOLD if bold else FONT_LATIN
    runs: list[tuple[str, str]] = []
    for char in text:
        face = _cjk_face_for(char) if _is_cjk(char) else latin
        if runs and runs[-1][0] == face:
            runs[-1] = (face, runs[-1][1] + char)
        else:
            runs.append((face, char))
    return runs


#: /F bit 2 on an annotation: Hidden.
_ANNOT_HIDDEN = 2

#: Left and right breathing room inside a widget box, in points.
_PAD = 2.0

#: Below this the value is a smudge, and an unreadable particular is worse
#: than one that visibly overflows its box.
_MIN_SIZE = 4.0

#: CR'S OWN SIZE, read out of the template rather than guessed: 287 of the
#: form's 318 text widgets carry `/DA = "/PMingLiU 12 Tf 0 g"`, and the rest
#: are 9pt, 10pt, or 0 (auto). Nothing on Form NAR1 is set at 10pt by default.
#:
#: THIS WAS 10.0 AND THAT WAS THE "the fonts look different" BUG. Every value
#: on every page rendered a sixth smaller than CR sets it, which beside GSHK's
#: own specimen reads as a different typeface rather than as a smaller one --
#: the face itself was never wrong. Measured 2026-09-02: Tinos-Bold's advance
#: widths are identical to Times New Roman Bold's to within 0.001pt on every
#: sample string, and at 12pt the two are not visually separable, so the
#: metric-compatible substitute stays. Do not "fix" the typography here; if a
#: value looks wrong, check the size it was drawn at first.
DEFAULT_SIZE = 12.0

#: Baseline-to-baseline distance as a multiple of the point size, for the
#: fields CR sizes to hold more than one line.
_LEADING = 1.15


def measure(text: str, size: float, *, bold: bool = True) -> float:
    """Advance width of `text` at `size`, summed across its script runs."""
    return sum(pdfmetrics.stringWidth(chunk, font, size)
               for font, chunk in split_runs(text, bold=bold))


def fit_size(text: str, width: float, *, start: float = DEFAULT_SIZE,
             minimum: float = _MIN_SIZE, bold: bool = True) -> float:
    """The largest size at or below `start` whose text fits `width`."""
    size = start
    usable = width - 2 * _PAD
    while size > minimum and measure(text, size, bold=bold) > usable:
        size -= 0.25
    return round(max(size, minimum), 2)


def draw_position(text: str, rect, *, size: float, quadding=None,
                  bold: bool = True) -> float:
    """The x the text starts at, honouring the field's /Q alignment.

    CR quads the company name and the BRN header CENTRE (`/Q = 1`) and its own
    filed returns render them that way. Everything else carries no `/Q` and is
    left-aligned. Getting this wrong is invisible to every value-and-font
    assertion in this file and obvious the moment anyone lays the two
    documents side by side -- which is how it was found.
    """
    x0, _, x1, _ = (float(v) for v in rect)
    width = measure(text, size, bold=bold)
    quad = int(quadding) if quadding is not None else 0
    if quad == 1:                      # centred
        return x0 + ((x1 - x0) - width) / 2
    if quad == 2:                      # right-aligned
        return x1 - _PAD - width
    return x0 + _PAD                   # left, and the default


def wrap(text: str, width: float, size: float, *, bold: bool = True
         ) -> list[str]:
    """`text` broken into lines that each fit `width`, greedily on spaces.

    A word longer than the whole line is left on a line of its own and
    overflows rather than being hyphenated or cut: it is somebody's building
    name or email address, and a statutory return must not invent a break in
    one.

    A value that already fits comes back VERBATIM, whitespace and all. Going
    through `split()` unconditionally cost `_company_name` the double space it
    deliberately puts between the English and Chinese names -- so the one
    thing this function must not do to a value it is not wrapping is touch it.
    """
    if measure(text, size, bold=bold) <= width:
        return [text]
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and measure(candidate, size, bold=bold) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _lines_that_fit(height: float, size: float) -> int:
    """How many lines of `size` CR's box has room for. At least one, because a
    box too short for its own nominal size still has to show its value."""
    return max(1, int((height - _PAD) // (size * _LEADING)))


def layout(text: str, rect, *, size: float = DEFAULT_SIZE, bold: bool = True
           ) -> tuple[list[str], float]:
    """The lines to draw and the size to draw them at.

    Shrinking is the LAST resort, not the first. CR sizes several boxes to
    hold two or three lines -- the presenter's address is 185pt wide and 66pt
    tall at 9pt -- and the single-line renderer shrank GSHK's full address to
    about 4pt to fit it across, which is the "reduced to a grey smear" end of
    `_MIN_SIZE` rather than the two tidy lines CR's own form shows. So the
    value is WRAPPED into the lines the box can hold, and only shrunk when
    even that will not fit.
    """
    x0, y0, x1, y1 = (float(v) for v in rect)
    usable = (x1 - x0) - 2 * _PAD
    height = y1 - y0
    current = size
    while current > _MIN_SIZE:
        lines = wrap(text, usable, current, bold=bold)
        if len(lines) <= _lines_that_fit(height, current):
            return lines, round(current, 2)
        current -= 0.25
    # At the floor, take whatever the box holds and let it overflow visibly.
    return wrap(text, usable, _MIN_SIZE, bold=bold), _MIN_SIZE


def draw_value(canvas, text: str, rect, *, size: float = DEFAULT_SIZE,
               bold: bool = True, quadding=None, field: str | None = None
               ) -> float:
    """Draw one value inside its widget rectangle. Returns the size used.

    Raises `AppearanceError` if the face `split_runs` selected for some
    character in `text` has no glyph for it. Left unchecked, reportlab does
    not raise here either: it maps the codepoint to glyph 0 (.notdef) and
    draws nothing -- no exception, no log line. That is how a director's
    Chinese surname rendered as a blank on a filed-looking NAR1, measured
    against real DEV data (U+6768, a top-ten Hong Kong surname, among them).
    A statutory return that silently drops a character from someone's name
    is worse than one that fails to generate; `field` names which one so the
    failure is actionable rather than a stack trace pointing at a font call.
    All runs are checked before anything is drawn, so a failure never leaves
    a half-drawn value on the page.
    """
    x0, y0, x1, y1 = (float(v) for v in rect)
    for font, chunk in split_runs(text, bold=bold):
        missing = _uncoverable(font, chunk)
        if missing:
            codepoints = ", ".join(
                f"{char!r} (U+{ord(char):04X})" for char in missing)
            where = f" for field {field!r}" if field else ""
            raise AppearanceError(
                f"cannot draw {codepoints}{where}: no glyph in {font} for "
                f"it. reportlab would silently substitute nothing rather "
                f"than raise, which is how this went unnoticed before."
            )
    lines, size = layout(text, rect, size=size, bold=bold)

    leading = size * _LEADING
    if len(lines) > 1:
        # A WRAPPED value starts at the TOP of its box, because CR's tall
        # boxes are tall to hold several lines and its own returns begin them
        # against the caption -- the presenter's address sits beside "地址
        # Address:", not floating in the middle of the panel below it.
        y = y1 - _PAD - size * 0.82
    else:
        # A single line is centred, which is what the tall one-value cells
        # want: section 11's Total row is 108pt deep and holds one figure,
        # and CR prints it in the middle.
        y = y0 + ((y1 - y0) - size * 0.72) / 2 + size * 0.06

    canvas.setFillColorRGB(0, 0, 0)
    for line in lines:
        x = draw_position(line, rect, size=size, quadding=quadding, bold=bold)
        for font, chunk in split_runs(line, bold=bold):
            canvas.setFont(font, size)
            canvas.drawString(x, y, chunk)
            x += pdfmetrics.stringWidth(chunk, font, size)
        y -= leading
    return size


#: `/DA` looks like "/PMingLiU 12 Tf 0 g" -- the operand before `Tf`.
_DA_SIZE = re.compile(r"/\S+\s+([\d.]+)\s+Tf")


def da_size(da) -> float | None:
    """The point size CR set on this field, or None for "CR did not say".

    A `/DA` size of **0** is the PDF spec's auto-size, which is also None
    here: the caller has the box and works it out. Anything unparseable is
    None too, so a template CR re-issues with a different `/DA` syntax falls
    back to the form's own 12pt rather than to nothing.
    """
    match = _DA_SIZE.search(str(da or ""))
    if not match:
        return None
    try:
        size = float(match.group(1))
    except ValueError:
        return None
    return size or None


def _auto_size(rect) -> float:
    """The starting size for a field CR marked auto (`0 Tf`).

    Capped at the form's own 12pt rather than filling the box: `fill_11_P.8`
    is the 25pt-tall signature rule, and a height-derived size would set the
    signatory's name at 20pt beside a 12pt return.
    """
    _, y0, _, y1 = (float(v) for v in rect)
    return min(DEFAULT_SIZE, max(_MIN_SIZE, (float(y1) - float(y0) - _PAD)
                                 / _LEADING))


#: The tick CR asks for -- "請在適用的空格內加上 ✓ 號" -- as a stroked path
#: rather than a glyph, given as (x, y) fractions of the widget box.
_TICK = ((0.18, 0.46), (0.42, 0.20), (0.86, 0.78))


def draw_tick(canvas, rect) -> None:
    """Draw a checkmark inside a checkbox widget's rectangle.

    WHY THIS IS DRAWN AND NOT LEFT TO THE WIDGET. CR's template does carry a
    complete `/On` appearance stream -- it sets ZapfDingbats '4' -- so a
    viewer that renders form widgets shows the tick correctly, and one that
    does not shows an UNTICKED box. That is not a cosmetic difference: the
    unticked boxes are section 3's company type, section 14's "members are
    listed in Schedule 1" and section 16's statement, so the same bytes read
    as a different statutory declaration depending on the renderer. It is the
    identical failure `bake()` exists to end for text, left in place for the
    ticks because they are annotations rather than values.
    """
    x0, y0, x1, y1 = (float(v) for v in rect)
    width, height = x1 - x0, y1 - y0
    canvas.saveState()
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(max(0.9, min(width, height) * 0.12))
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    path = canvas.beginPath()
    (ax, ay), (bx, by), (cx, cy) = _TICK
    path.moveTo(x0 + ax * width, y0 + ay * height)
    path.lineTo(x0 + bx * width, y0 + by * height)
    path.lineTo(x0 + cx * width, y0 + cy * height)
    canvas.drawPath(path, stroke=1, fill=0)
    canvas.restoreState()


def _is_ticked(obj) -> bool:
    """Whether this button widget is in an ON state.

    `/AS` is what a viewer draws and `/V` is what the field holds; a widget
    that has one without the other is still ticked as far as the return is
    concerned, so either counts. `/Off` never does.
    """
    for key in ("/AS", "/V"):
        state = obj.get(key)
        if state is not None and str(state) not in ("/Off", "Off", ""):
            return True
    return False


def bake(pdf_bytes: bytes, *, sizes: dict[str, float] | None = None,
         regular: frozenset[str] | set[str] | None = None) -> bytes:
    """Draw every field value as page content and hide the widgets.

    `sizes` maps a field's ORIGINAL template name to a point size, overriding
    the field's own `/DA` for the handful read off a real filed return rather
    than off the template -- the BRN at 14pt and the company name at 12pt.
    Names carry the renderer's per-page suffix, so the lookup is on the part
    before `__p`. Everything else takes the size CR set on the field itself.

    `regular` names the fields CR sets in the REGULAR face rather than bold --
    the presenter's block, which identifies who filed the return rather than
    stating anything about the company. Everything else is bold.
    """
    register_fonts()
    sizes = sizes or {}
    regular = regular or frozenset()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    # clone_from, rather than building a writer and adding pages to it one at a
    # time. `merge_page` on a page that is not yet attached to a writer is
    # deprecated in pypdf 6.16 -- its own note says the approach "has proved
    # being unreliable" -- and removed in 7.0. `pypdf` is declared `>=6.16.1`
    # with no upper bound, so a routine `uv sync` can resolve 7.0, and the
    # failure mode would be every client-verification attachment silently
    # ceasing to render.
    writer = PdfWriter(clone_from=reader)

    for page in writer.pages:
        box = page.mediabox
        buffer = io.BytesIO()
        layer = rl_canvas.Canvas(
            buffer, pagesize=(float(box.width), float(box.height)))
        drew = False

        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            kind = obj.get("/FT")
            if kind == "/Btn":
                if not _is_ticked(obj):
                    continue
                draw_tick(layer, obj["/Rect"])
                obj[NameObject("/F")] = NumberObject(
                    int(obj.get("/F", 0)) | _ANNOT_HIDDEN)
                drew = True
                continue
            if kind != "/Tx":
                continue
            value = obj.get("/V")
            if value is None or not str(value).strip():
                continue
            name = str(obj.get("/T") or "").split("__p")[0]
            size = sizes.get(name) or da_size(obj.get("/DA"))
            draw_value(layer, str(value), obj["/Rect"],
                       size=size or _auto_size(obj["/Rect"]),
                       bold=name not in regular,
                       quadding=obj.get("/Q"),
                       field=name)
            obj[NameObject("/F")] = NumberObject(
                int(obj.get("/F", 0)) | _ANNOT_HIDDEN)
            drew = True

        layer.save()
        if drew:
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])

    acroform = writer._root_object.get("/AcroForm")
    if acroform is not None:
        # Already carried across by clone_from; only the flag needs clearing.
        # The layer IS the appearance now. Leaving NeedAppearances true invites
        # a viewer to discard it and redraw from /DA -- the original defect.
        # DELETED rather than set to BooleanObject(False): pypdf's
        # BooleanObject has no __bool__ override, so any instance -- true OR
        # false -- is truthy in Python (verified against pypdf 6.16.1), which
        # would make `acroform.get("/NeedAppearances")` read as set either way
        # once the bytes are re-parsed. The PDF spec's own default for an
        # ABSENT key is false, so deleting it is both correct and what a
        # re-parsed reader actually reports as falsy.
        acroform = acroform.get_object()
        if "/NeedAppearances" in acroform:
            del acroform[NameObject("/NeedAppearances")]

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
