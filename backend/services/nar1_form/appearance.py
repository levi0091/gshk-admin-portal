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

#: Sizes read off CR's own returns.
DEFAULT_SIZE = 10.0


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
    runs = split_runs(text, bold=bold)
    for font, chunk in runs:
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
    size = fit_size(text, x1 - x0, start=size, bold=bold)
    # Vertically centre the glyph box. 0.72 approximates cap height for both
    # faces; the correction keeps a 10pt value off the rule beneath it.
    y = y0 + ((y1 - y0) - size * 0.72) / 2 + size * 0.06
    x = draw_position(text, rect, size=size, quadding=quadding, bold=bold)
    canvas.setFillColorRGB(0, 0, 0)
    for font, chunk in runs:
        canvas.setFont(font, size)
        canvas.drawString(x, y, chunk)
        x += pdfmetrics.stringWidth(chunk, font, size)
    return size


def bake(pdf_bytes: bytes, *, sizes: dict[str, float] | None = None,
         regular: frozenset[str] | set[str] | None = None) -> bytes:
    """Draw every field value as page content and hide the widgets.

    `sizes` maps a field's ORIGINAL template name to a point size, for the
    handful CR sets larger than the rest -- the BRN at 14pt and the company
    name at 12pt. Names carry the renderer's per-page suffix, so the lookup
    is on the part before `__p`.

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
            if obj.get("/FT") != "/Tx":
                continue
            value = obj.get("/V")
            if value is None or not str(value).strip():
                continue
            name = str(obj.get("/T") or "").split("__p")[0]
            draw_value(layer, str(value), obj["/Rect"],
                       size=sizes.get(name, DEFAULT_SIZE),
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
