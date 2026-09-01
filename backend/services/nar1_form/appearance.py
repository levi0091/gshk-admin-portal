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

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: reportlab's names for the faces. Prefixed so they cannot collide with a
#: font another part of the app registers in the same process.
FONT_LATIN_BOLD = "NAR1-Bold"
FONT_LATIN = "NAR1-Regular"
FONT_CJK = "NAR1-CJK"

_FILES = {
    FONT_LATIN_BOLD: "Tinos-Bold.ttf",
    FONT_LATIN: "Tinos-Regular.ttf",
    FONT_CJK: "NotoSerifTC-Bold.ttf",
}

_registered = False


class AppearanceError(RuntimeError):
    """The text layer could not be drawn."""


def register_fonts() -> None:
    """Register the three faces with reportlab. Idempotent and cheap after
    the first call, which matters because it runs on every render."""
    global _registered
    if _registered:
        return
    for name, filename in _FILES.items():
        path = FONT_DIR / filename
        if not path.exists():
            raise AppearanceError(
                f"the NAR1 font {filename} is missing from {FONT_DIR}. It is a "
                f"runtime asset, not documentation -- see fonts/README.md"
            )
        pdfmetrics.registerFont(TTFont(name, str(path)))
    _registered = True


def _is_cjk(char: str) -> bool:
    """CJK ideographs, radicals, and the fullwidth forms that travel with
    them. Deliberately NOT all of 'not ASCII': accented Latin belongs in the
    Latin face, and routing it to the CJK one would change its shape."""
    code = ord(char)
    return (0x2E80 <= code <= 0x9FFF     # radicals through CJK Unified
            or 0xF900 <= code <= 0xFAFF  # compatibility ideographs
            or 0xFF00 <= code <= 0xFFEF)  # fullwidth / halfwidth forms


def split_runs(text: str, *, bold: bool = True) -> list[tuple[str, str]]:
    """Split `text` into consecutive (font name, chunk) runs.

    Per character, because a Hong Kong address is routinely half English and
    half Chinese and a single font for the whole value would drop one half.
    """
    latin = FONT_LATIN_BOLD if bold else FONT_LATIN
    runs: list[tuple[str, str]] = []
    for char in text:
        face = FONT_CJK if _is_cjk(char) else latin
        if runs and runs[-1][0] == face:
            runs[-1] = (face, runs[-1][1] + char)
        else:
            runs.append((face, char))
    return runs


import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject
from reportlab.pdfgen import canvas as rl_canvas

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
               bold: bool = True, quadding=None) -> float:
    """Draw one value inside its widget rectangle. Returns the size used."""
    x0, y0, x1, y1 = (float(v) for v in rect)
    size = fit_size(text, x1 - x0, start=size, bold=bold)
    # Vertically centre the glyph box. 0.72 approximates cap height for both
    # faces; the correction keeps a 10pt value off the rule beneath it.
    y = y0 + ((y1 - y0) - size * 0.72) / 2 + size * 0.06
    x = draw_position(text, rect, size=size, quadding=quadding, bold=bold)
    canvas.setFillColorRGB(0, 0, 0)
    for font, chunk in split_runs(text, bold=bold):
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
    writer = PdfWriter()

    for page in reader.pages:
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
                       quadding=obj.get("/Q"))
            obj[NameObject("/F")] = NumberObject(
                int(obj.get("/F", 0)) | _ANNOT_HIDDEN)
            drew = True

        layer.save()
        if drew:
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])
        writer.add_page(page)

    acroform = reader.trailer["/Root"].get("/AcroForm")
    if acroform is not None:
        # DictionaryObject.get() is plain dict.get() underneath -- unlike
        # __getitem__, it does NOT resolve an IndirectObject. Without
        # get_object() here, .clone() runs on the reference itself and
        # raises "'IndirectObject' object does not support item assignment"
        # a few lines down. Verified against pypdf 6.16.1.
        cloned = acroform.get_object().clone(writer)
        # The layer IS the appearance now. Leaving this true invites a viewer
        # to discard it and redraw from /DA -- the original defect. REMOVED
        # rather than set to BooleanObject(False): pypdf's BooleanObject has
        # no __bool__ override, so any instance -- true OR false -- is
        # truthy in Python (verified against pypdf 6.16.1), which would make
        # `acroform.get("/NeedAppearances")` read as set either way once the
        # bytes are re-parsed. The PDF spec's own default for an ABSENT key
        # is false, so deleting it is both correct and what a re-parsed
        # reader actually reports as falsy.
        if "/NeedAppearances" in cloned:
            del cloned[NameObject("/NeedAppearances")]
        writer._root_object[NameObject("/AcroForm")] = writer._add_object(cloned)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
