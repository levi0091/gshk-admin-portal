# Block A — NAR1 Form Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generated NAR1 render identically in every viewer, in the same fonts CR uses, across CR's full static nine-page form — and give the client-review preview room to be read.

**Architecture:** The values are currently written as AcroForm field values whose appearance streams point at a non-embedded Chinese font, under a `NeedAppearances` flag that invites viewers to regenerate them anyway. We keep writing `/V` (so the data stays machine-readable and the existing test suite keeps working), add a **baked text layer** drawn with reportlab in embedded metric-compatible fonts, hide the widgets so nothing paints over that layer, and turn `NeedAppearances` off. Separately, the page composer stops dropping pages whose section is empty, because CR's form is static.

**Tech Stack:** Python 3.12 · pypdf 6.16.1 · reportlab (already a dependency) · pytest · React/Vitest for the one frontend change · `fontTools` as a **build-time only** tool

**Spec:** `docs/superpowers/specs/2026-09-01-nar1-client-approval-and-form-fidelity-design.md` (§1, §1b, §3)

## Global Constraints

- **Never use bare `pip`.** Dependencies are managed with `uv`: `uv add <pkg>`, `uv sync`, `uv run pytest`. `pyproject.toml` is the source of truth and `uv.lock` is committed.
- **Windows alembic quirk:** invoke alembic from the venv directly (`.venv\Scripts\alembic.exe`), never `uv run alembic`. *(No migrations in this block — noted because it applies repo-wide.)*
- **`docs/` is gitignored repo-wide.** Runtime assets must never live there. Font files go in `backend/services/nar1_form/fonts/`.
- **Tests are part of the definition of done.** Every change here ships with tests; no merge without CI green.
- **Never push to `main`.** Work happens on `dev` or a feature branch off it. Merging to `main` deploys to PROD and the live Companies Registry, and needs Levi's explicit per-merge consent.
- **Console encoding is cp1252 on this machine.** Keep script `print()` output ASCII, or set `PYTHONIOENCODING=utf-8`.
- Exact font sizes, from the reference return: **10pt** ordinary field values, **14pt** the BRN in the header box, **12pt** the company name in field 1.
- Exact CJK instancing axis value: **`wght=700`**.
- Brand tokens are fixed and hardcoded; this block touches no colours.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/services/nar1_form/fonts/Tinos-Bold.ttf` | Latin bold face — all field values |
| `backend/services/nar1_form/fonts/Tinos-Regular.ttf` | Latin regular face — presenter block |
| `backend/services/nar1_form/fonts/NotoSerifTC-Bold.ttf` | CJK face, instanced to wght=700 |
| `backend/services/nar1_form/fonts/README.md` | Provenance, licences, and how to regenerate the CJK static |
| `backend/scripts/build_cjk_font.py` | Build-time: instance the CJK variable font. Not imported at runtime |
| `backend/services/nar1_form/appearance.py` | **New.** Registers fonts, splits text into script runs, draws the baked layer, hides widgets |
| `backend/services/nar1_form/fill.py` | Modified: `_compose` stops dropping pages; `_render` calls the overlay and clears `NeedAppearances` |
| `backend/tests/test_nar1_form_appearance.py` | **New.** Font embedding, run splitting, fit-shrinking, hidden widgets, no `NeedAppearances` |
| `backend/tests/test_nar1_form_fill.py` | Modified: add static-page-set assertions |
| `frontend/src/components/case/StageClientVerification.jsx` | Modified: preview base height 460 → 690 |
| `frontend/src/components/case/stages.test.jsx` | Modified: assert the new height |

---

## Task 1: Vendor the fonts

**Files:**
- Create: `backend/services/nar1_form/fonts/Tinos-Bold.ttf`
- Create: `backend/services/nar1_form/fonts/Tinos-Regular.ttf`
- Create: `backend/services/nar1_form/fonts/NotoSerifTC-Bold.ttf`
- Create: `backend/services/nar1_form/fonts/README.md`
- Create: `backend/scripts/build_cjk_font.py`

**Interfaces:**
- Consumes: nothing.
- Produces: three `.ttf` files at the paths above. Task 2 loads them by those exact names.

- [ ] **Step 1: Download the two Latin faces**

```bash
cd backend/services/nar1_form && mkdir -p fonts && cd fonts
curl -sL -o Tinos-Bold.ttf \
  "https://raw.githubusercontent.com/googlefonts/Tinos/main/fonts/ttf/Tinos-Bold.ttf"
curl -sL -o Tinos-Regular.ttf \
  "https://raw.githubusercontent.com/googlefonts/Tinos/main/fonts/ttf/Tinos-Regular.ttf"
```

Expected: `Tinos-Bold.ttf` ≈ 597,880 bytes, `Tinos-Regular.ttf` ≈ 521,588 bytes. Verify with `file Tinos-Bold.ttf` — must say `TrueType Font data`.

- [ ] **Step 2: Write the CJK build script**

`backend/scripts/build_cjk_font.py`. This runs **once, by a developer**, and its output is committed. It is never imported by the application — which is what keeps `fontTools` out of the runtime dependencies.

```python
"""Instance Noto Serif TC's variable font to Bold and save it statically.

BUILD-TIME ONLY. Run this by hand when the CJK face needs regenerating; the
result is committed. Nothing in the application imports it, so `fonttools`
stays a developer tool rather than a runtime dependency.

    uv run --with fonttools --with brotli python scripts/build_cjk_font.py

WHY THIS EXISTS AT ALL. Registering the variable font directly gives you its
DEFAULT instance, which for Noto Serif TC is ExtraLight -- so Chinese company
names would render hairline-thin beside bold Latin ones. There is no static
TrueType Bold published for this family, and reportlab cannot read the
PostScript-outline OTF build (`TTFError: postscript outlines are not
supported`), so instancing the variable TTF ourselves is the only route.
"""
import sys
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

SOURCE = ("https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
          "Serif/Variable/TTF/Subset/NotoSerifTC-VF.ttf")
TARGET = Path(__file__).resolve().parents[1] / "services" / "nar1_form" / "fonts" / "NotoSerifTC-Bold.ttf"
WEIGHT = 700


def main() -> int:
    print(f"downloading {SOURCE}")
    raw = urllib.request.urlopen(SOURCE, timeout=180).read()
    cache = TARGET.parent / "_NotoSerifTC-VF.ttf"
    cache.write_bytes(raw)
    try:
        font = TTFont(cache)
        static = instancer.instantiateVariableFont(font, {"wght": WEIGHT})
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        static.save(TARGET)
    finally:
        cache.unlink(missing_ok=True)
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes) at wght={WEIGHT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run it**

```bash
cd backend && uv run --with fonttools --with brotli python scripts/build_cjk_font.py
```

Expected: `wrote .../NotoSerifTC-Bold.ttf (≈10000000 bytes) at wght=700`.

- [ ] **Step 4: Record provenance**

`backend/services/nar1_form/fonts/README.md`:

```markdown
# Fonts for the generated NAR1

Committed here, **not** in `docs/`, which is gitignored repo-wide: a font that
lives there is present on one laptop and absent from CI, Railway, and every
fresh clone. These are runtime assets, exactly like `form/NAR1_fillable.pdf`.

| File | Family | Licence | Source |
|---|---|---|---|
| `Tinos-Bold.ttf` | Tinos Bold | Apache-2.0 | github.com/googlefonts/Tinos |
| `Tinos-Regular.ttf` | Tinos Regular | Apache-2.0 | github.com/googlefonts/Tinos |
| `NotoSerifTC-Bold.ttf` | Noto Serif TC | OFL-1.1 | Built by `scripts/build_cjk_font.py` |

## Why Tinos and not Times New Roman

CR's own returns fill values in Times New Roman Bold. Times New Roman is
Monotype-licensed and cannot be redistributed in this repo or a Railway image.
Tinos is **metrically identical** to it: measured across company names,
addresses, amounts and email addresses, the advance-width delta at 10pt is
exactly 0.0000pt. Nothing wraps or overflows differently.

## Regenerating the CJK face

    uv run --with fonttools --with brotli python scripts/build_cjk_font.py

Noto Serif TC publishes a variable font whose **default instance is
ExtraLight**, and no static TrueType Bold. The script instances it to
`wght=700`. Do not swap in the `SubsetOTF` build: reportlab cannot read
PostScript outlines and raises `TTFError` on it.
```

- [ ] **Step 5: Confirm the fonts are not swept up by .gitignore**

```bash
cd .. && git check-ignore -v backend/services/nar1_form/fonts/Tinos-Bold.ttf; echo "exit=$? (1 means NOT ignored, which is what we want)"
git add --dry-run backend/services/nar1_form/fonts/
```

Expected: `exit=1`, and `git add --dry-run` lists all four files. If any is ignored, fix `.gitignore` before continuing — a font that silently does not commit fails on Railway, not here.

- [ ] **Step 6: Commit**

```bash
git add backend/services/nar1_form/fonts/ backend/scripts/build_cjk_font.py
git commit -m "feat(nar1): vendor Tinos and Noto Serif TC for the generated form

Tinos is metric-identical to Times New Roman (0.0000pt delta at 10pt) and
Apache-2.0, so it can ship where timesbd.ttf cannot. The CJK face is instanced
from the variable font to wght=700 by a build-time script, because the
variable default is ExtraLight and no static TrueType Bold is published."
```

---

## Task 2: Script-run splitting and font registration

**Files:**
- Create: `backend/services/nar1_form/appearance.py`
- Test: `backend/tests/test_nar1_form_appearance.py`

**Interfaces:**
- Consumes: the three `.ttf` files from Task 1.
- Produces:
  - `FONT_LATIN_BOLD: str = "NAR1-Bold"`, `FONT_LATIN: str = "NAR1-Regular"`, `FONT_CJK: str = "NAR1-CJK"` — reportlab font names.
  - `register_fonts() -> None` — idempotent.
  - `split_runs(text: str, *, bold: bool = True) -> list[tuple[str, str]]` — `[(font_name, chunk), ...]` in order.
  - `AppearanceError(RuntimeError)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_nar1_form_appearance.py`:

```python
"""The baked text layer: fonts, run splitting, fitting, and what it hides."""
import io

import pytest
from pypdf import PdfReader

from services.nar1_form import appearance as ap


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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && uv run pytest tests/test_nar1_form_appearance.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.nar1_form.appearance'`.

- [ ] **Step 3: Write the minimal implementation**

`backend/services/nar1_form/appearance.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_nar1_form_appearance.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/nar1_form/appearance.py backend/tests/test_nar1_form_appearance.py
git commit -m "feat(nar1): register the form fonts and split values into script runs

Per-character, because a Hong Kong address is routinely half English and half
Chinese; one face for the whole value drops one half. Accented Latin stays in
the Latin face rather than being swept into CJK by a not-ASCII test."
```

---

## Task 3: Draw the baked layer

**Files:**
- Modify: `backend/services/nar1_form/appearance.py`
- Test: `backend/tests/test_nar1_form_appearance.py`

**Interfaces:**
- Consumes: `register_fonts`, `split_runs`, `FONT_*` from Task 2.
- Produces:
  - `measure(text: str, size: float, *, bold: bool = True) -> float` — total advance width in points.
  - `fit_size(text, width, *, start=10.0, minimum=4.0, bold=True) -> float`
  - `draw_value(canvas, text, rect, *, size=10.0, bold=True) -> float` — returns the size actually used.
  - `bake(pdf_bytes: bytes, *, sizes: dict[str, float] | None = None) -> bytes` — the whole-document entry point Task 4 calls.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_nar1_form_appearance.py`:

```python
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
    rather than run off the edge of the field."""
    ap.register_fonts()
    long_value = "Flat A, 39/F, Block 2, Something Very Long Gardens, Kowloon"
    size = ap.fit_size(long_value, width=90.0)
    assert size < 10.0
    assert ap.measure(long_value, size) <= 90.0 - 4.0


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
```

These two need `from services.nar1_form import field_map as fm` at the top of
the test file.

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_nar1_form_appearance.py -v
```

Expected: the measuring/fitting tests FAIL with `AttributeError: module ... has no attribute 'measure'`; the baking tests FAIL on `NeedAppearances` still being true.

- [ ] **Step 3: Implement measuring, fitting and drawing**

Append to `backend/services/nar1_form/appearance.py`:

```python
import io

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, NumberObject
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


def draw_value(canvas, text: str, rect, *, size: float = DEFAULT_SIZE,
               bold: bool = True) -> float:
    """Draw one value inside its widget rectangle. Returns the size used."""
    x0, y0, x1, y1 = (float(v) for v in rect)
    size = fit_size(text, x1 - x0, start=size, bold=bold)
    # Vertically centre the glyph box. 0.72 approximates cap height for both
    # faces; the correction keeps a 10pt value off the rule beneath it.
    y = y0 + ((y1 - y0) - size * 0.72) / 2 + size * 0.06
    x = x0 + _PAD
    canvas.setFillColorRGB(0, 0, 0)
    for font, chunk in split_runs(text, bold=bold):
        canvas.setFont(font, size)
        canvas.drawString(x, y, chunk)
        x += pdfmetrics.stringWidth(chunk, font, size)
    return size


def bake(pdf_bytes: bytes, *, sizes: dict[str, float] | None = None) -> bytes:
    """Draw every field value as page content and hide the widgets.

    `sizes` maps a field's ORIGINAL template name to a point size, for the
    handful CR sets larger than the rest -- the BRN at 14pt and the company
    name at 12pt. Names carry the renderer's per-page suffix, so the lookup
    is on the part before `__p`.
    """
    register_fonts()
    sizes = sizes or {}
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
                       size=sizes.get(name, DEFAULT_SIZE))
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
        cloned = acroform.clone(writer)
        # The layer IS the appearance now. Leaving this true invites a viewer
        # to discard it and redraw from /DA -- the original defect.
        cloned[NameObject("/NeedAppearances")] = BooleanObject(False)
        writer._root_object[NameObject("/AcroForm")] = writer._add_object(cloned)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
```

- [ ] **Step 4: Wire it into the renderer**

In `backend/services/nar1_form/fill.py`, add the import near the other local imports:

```python
from services.nar1_form import appearance
from services.nar1_form import field_map as fm
```

Add the size table just below `DEFAULT_PRESENTER`:

```python
#: The sizes CR uses that are not the 10pt default, keyed by the field's name
#: on the template. Read off a real filed return rather than guessed: the BRN
#: in the header box is 14pt on EVERY page, and the company name in field 1
#: is 12pt.
#:
#: Built from field_map's own constants rather than a regex over field names.
#: `fill_1_P.6` is a BRN header and `fill_6_P.6` is a director's surname --
#: a pattern loose enough to catch every header also catches those.
def _br_number_fields() -> set[str]:
    groups = (fm.MAIN_1, fm.MAIN_2, fm.SECRETARY_INDIVIDUAL,
              fm.SECRETARY_CORPORATE, fm.DIRECTOR_INDIVIDUAL,
              fm.DIRECTOR_CORPORATE_HEADER, fm.RESERVE_DIRECTOR,
              fm.MEMBERS_AND_SIGNATURE, fm.SCHEDULE_1, fm.SCHEDULE_2)
    names = {group["br_number"] for group in groups if "br_number" in group}
    for page in range(fm.PAGE_SHEET_A, fm.PAGE_SHEET_E + 1):
        names.add(fm.sheet_header(page)["br_number"])
    return names


FIELD_SIZES = {name: 14.0 for name in _br_number_fields()}
FIELD_SIZES[fm.MAIN_1["company_name"]] = 12.0
```

> Confirm the constant names in `field_map.py` before pasting this — the
> Schedule groups may be named differently. `grep -n '"br_number"'
> services/nar1_form/field_map.py` lists all eleven; every one of them must
> end up in the set, and the test in the next step checks that.

Then in `_render`, replace the `set_need_appearances_writer(True)` call and its
comment with nothing, and change the final write so the bytes go through the
baker. The tail of `_render` becomes:

```python
    # Read-only, because the client is being asked to APPROVE this document,
    # not to edit it. Bit 1 of /Ff is ReadOnly.
    for page in writer.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            flags = int(obj.get("/Ff", 0)) | 1
            obj[NameObject("/Ff")] = NumberObject(flags)

    # Every page copy carries its own clone of the template's fonts and CR's
    # logo, so a nine-page return weighs 6.3MB before this and 0.9MB after --
    # the difference between a document that emails and one that bounces.
    # Deduplicates identical objects only; nothing visible changes.
    writer.compress_identical_objects()

    buffer = io.BytesIO()
    writer.write(buffer)
    # The values are drawn as page content in fonts we embed, and the widgets
    # are hidden. Until this call the document still renders through CR's
    # non-embedded /PMingLiU, which is what made the emailed copy and the
    # portal preview disagree.
    return appearance.bake(buffer.getvalue(), sizes=FIELD_SIZES)
```

Also delete the now-stale logging suppression at the top of the file and its
comment block, since nothing asks the viewer to build appearances any more:

```python
logging.getLogger("pypdf.generic._appearance_stream").setLevel(logging.ERROR)
```

Leave the `import logging` if anything else uses it; remove it if not.

- [ ] **Step 5: Run the appearance tests**

```bash
cd backend && uv run pytest tests/test_nar1_form_appearance.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the whole existing form suite — nothing may regress**

```bash
cd backend && uv run pytest tests/test_nar1_form_fill.py -v
```

Expected: all pass. `values_of()` reads `/V`, which is still written, so these assertions must be untouched. **If any fail, stop** — the fix has changed the data, not only its rendering.

- [ ] **Step 7: Commit**

```bash
git add backend/services/nar1_form/appearance.py backend/services/nar1_form/fill.py backend/tests/test_nar1_form_appearance.py
git commit -m "fix(nar1): draw form values as a baked layer in embedded fonts

Every valued field already had an appearance stream; they pointed at
/PMingLiU, which the template does not embed, under NeedAppearances=true,
which tells viewers to throw them away and redraw from /DA. Acrobat and
Outlook obeyed, pdfium largely did not, and the emailed return and the portal
preview rendered in different fonts.

Values are now page content in embedded Tinos Bold, with Noto Serif TC per
character for CJK, widgets hidden so nothing paints over them, and
NeedAppearances cleared. /V is still written, so the data stays readable and
the existing suite still asserts on it."
```

---

## Task 4: Emit CR's full static page set

**Files:**
- Modify: `backend/services/nar1_form/fill.py:520-545`
- Test: `backend/tests/test_nar1_form_fill.py`

**Interfaces:**
- Consumes: `fm.PAGE_*` constants, `_Pages.add` — both already exist.
- Produces: no new symbols. `render()`'s output gains pages.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_nar1_form_fill.py`:

```python
# ---------------------------------------------------------------------------
# CR's form is STATIC (client-confirmed 2026-09-01)
# ---------------------------------------------------------------------------

def test_the_return_is_always_CRs_nine_pages():
    """CR does not drop a section's page when the section is empty. The
    reference return carries an empty natural-person secretary page, an empty
    body-corporate director page and an empty reserve-director page, and files
    all three. Dropping them moved every later section's page number, which is
    what made the client's page references disagree with ours."""
    assert len(PdfReader(io.BytesIO(fill.render(build_xml()))).pages) == 9


def test_the_page_set_does_not_move_with_the_officer_mix():
    """The email tells the client 'Page 5: Director's details'. That is only
    true if page 5 is the director page for every company."""
    one = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    corp = PdfReader(io.BytesIO(fill.render(
        build_xml(corporate_directors=("ALPHA LTD",))))).pages
    assert len(one) == len(corp) == 9


def test_share_capital_is_on_page_2_and_directors_on_page_5():
    """The two page numbers hardcoded into the client email."""
    pages = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    assert "Share Capital" in (pages[1].extract_text() or "")
    assert "Director (Natural Person)" in (pages[4].extract_text() or "")


def test_continuation_sheets_are_still_conditional():
    """Those genuinely ARE overflow -- CR's form says 'Use Continuation Sheet
    C if more than 1 director is a natural person'."""
    plain = PdfReader(io.BytesIO(fill.render(build_xml()))).pages
    overflow = PdfReader(io.BytesIO(fill.render(
        build_xml(directors=("CHAN", "LEE", "WONG"))))).pages
    assert len(plain) == 9
    assert len(overflow) > 9
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && uv run pytest tests/test_nar1_form_fill.py -k "static or page_set or page_2 or continuation" -v
```

Expected: FAIL — `assert 6 == 9`.

- [ ] **Step 3: Make the five section pages unconditional**

In `backend/services/nar1_form/fill.py`, replace the officer block at lines 520-545 with:

```python
    # CR's NAR1 is a STATIC form: a section's page is filed whether or not the
    # section has content. The reference return carries an empty natural-person
    # secretary page, an empty body-corporate director page and an empty
    # reserve-director page, and files all three.
    #
    # These used to be conditional, so a typical private company rendered six
    # pages instead of nine and every section below the gap moved. The client
    # verification email names pages ("Page 5: Director's details"), so a page
    # set that shifts with the officer mix points the reader at the wrong
    # section. Continuation sheets stay conditional below -- those really are
    # overflow, and CR's own form says so.
    if ind_secs:
        values = _individual_officer(fm.SECRETARY_INDIVIDUAL, ind_secs[0],
                                     hk_only=True)
    else:
        values = {}
    values[fm.SECRETARY_INDIVIDUAL["br_number"]] = br_number
    pages.add(fm.PAGE_SECRETARY_INDIVIDUAL, values)

    if corp_secs:
        values = _corporate_officer(fm.SECRETARY_CORPORATE, corp_secs[0],
                                    hk_only=True)
    else:
        values = {}
    values[fm.SECRETARY_CORPORATE["br_number"]] = br_number
    pages.add(fm.PAGE_SECRETARY_CORPORATE, values)

    if ind_dirs:
        values = _individual_officer(fm.DIRECTOR_INDIVIDUAL, ind_dirs[0],
                                     hk_only=False)
    else:
        values = {}
    values[fm.DIRECTOR_INDIVIDUAL["br_number"]] = br_number
    pages.add(fm.PAGE_DIRECTOR_INDIVIDUAL, values)

    values = {fm.DIRECTOR_CORPORATE_HEADER["br_number"]: br_number}
    for slot, body in zip(fm.DIRECTOR_CORPORATE,
                          corp_dirs[:fm.DIRECTOR_CORPORATE_SLOTS]):
        values.update(_corporate_officer(slot, body, hk_only=False))
    pages.add(fm.PAGE_DIRECTOR_CORPORATE, values)

    if res_dirs:
        values = _individual_officer(fm.RESERVE_DIRECTOR, res_dirs[0],
                                     hk_only=False)
    else:
        values = {}
    values[fm.RESERVE_DIRECTOR["br_number"]] = br_number
    pages.add(fm.PAGE_RESERVE_DIRECTOR, values)
```

- [ ] **Step 4: Run the new tests**

```bash
cd backend && uv run pytest tests/test_nar1_form_fill.py -k "static or page_set or page_2 or continuation" -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full form suite**

```bash
cd backend && uv run pytest tests/test_nar1_form_fill.py tests/test_nar1_form_appearance.py -v
```

Expected: all pass. Two existing tests assert page counts and may need their expectations updated to 9 — read each one and confirm the new number is right before changing it. **Do not** relax an assertion that is catching a real problem; `test_the_printed_notes_are_dropped` asserts `< 16`, which 9 still satisfies.

- [ ] **Step 6: Check the attachment is still mailable**

```bash
cd backend && uv run python -c "
import sys; sys.path[:0]=['.','tests']
from tests.test_nar1_form_fill import build_xml
from services.nar1_form import fill
print('%.2f MB' % (len(fill.render(build_xml()))/1e6))
"
```

Expected: under 3 MB. Three more pages of CR's template are three more copies of its artwork, and `compress_identical_objects` is what keeps that flat — if this jumps past 3 MB, say so rather than proceeding.

- [ ] **Step 7: Commit**

```bash
git add backend/services/nar1_form/fill.py backend/tests/test_nar1_form_fill.py
git commit -m "fix(nar1): file CR's full nine-page form, empty sections included

CR does not drop a section's page when the section is empty -- the reference
return carries an empty natural-person secretary page, an empty body-corporate
director page and an empty reserve-director page, and files all three. We
dropped them, so a typical private company rendered six pages and every
section below the gap moved.

That is what made the client's page references disagree with ours: the
verification email says 'Page 5: Director's details', which is true of CR's
form and was not true of ours. Continuation sheets stay conditional -- those
really are overflow."
```

---

## Task 5: Give the client-review preview room to be read

**Files:**
- Modify: `frontend/src/components/case/StageClientVerification.jsx:211-249`
- Test: `frontend/src/components/case/stages.test.jsx`

**Interfaces:**
- Consumes: nothing from earlier tasks. Independently shippable.
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/case/stages.test.jsx`, in the client-verification describe block:

```jsx
it('gives the preview enough height to read a statutory return', async () => {
  renderClientVerification()
  const frame = await screen.findByLabelText('NAR1 preview')
  // 690px at 100% zoom. The return is nine A4 pages and the operator is
  // checking particulars against the company record, not glancing at it.
  expect(frame).toHaveStyle({ height: '690px' })
})
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npm run test -- stages.test.jsx -t "enough height"
```

Expected: FAIL — received `460px`.

- [ ] **Step 3: Change the height and the comment that explains it**

In `frontend/src/components/case/StageClientVerification.jsx`, the `<object>`'s
style becomes:

```jsx
            {/* Zoom grows the VIEWPORT, not a CSS transform. Scaling the
                element would scale its scrollbars and clip the page; a taller
                frame is what the embedded viewer actually reads as bigger. */}
            <object data={pdfUrl} type="application/pdf" aria-label="NAR1 preview"
                    className="pdf-frame"
                    style={{ height: Math.round(690 * zoom / 100) }}>
```

And update the stale reference in the "Open full screen" comment above it,
which still cites the old number:

```jsx
            {/* A tab, not a modal: the operator is checking this against the
                company record in another window, and even 690px of embedded
                viewer is not a whole nine-page statutory return. */}
```

- [ ] **Step 4: Run the test**

```bash
cd frontend && npm run test -- stages.test.jsx -t "enough height"
```

Expected: PASS.

- [ ] **Step 5: Run the full frontend suite**

```bash
cd frontend && npm run test
```

Expected: all pass. Another test may assert the old height — update it to 690 rather than deleting it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/case/StageClientVerification.jsx frontend/src/components/case/stages.test.jsx
git commit -m "feat(nar1): raise the client-review preview to 690px

460px showed roughly a third of an A4 page, and the operator is checking nine
pages of particulars against the company record."
```

---

## Task 6: Verify the whole block, visually and in CI

**Files:**
- Modify: `backend/tests/test_nar1_form_appearance.py` (one added test)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Render a real return and look at it**

```bash
cd backend && uv run python -c "
import sys; sys.path[:0]=['.','tests']
from tests.test_nar1_form_fill import build_xml
from services.nar1_form import fill
open('../nar1_check.pdf','wb').write(fill.render(build_xml()))
print('wrote nar1_check.pdf')
"
```

Open `nar1_check.pdf` and confirm by eye, against
`docs/Kanenas Holding Limited NAR1 2026.pdf`:

1. Nine pages, including the three empty section pages.
2. Values are a Times-like serif, not a Chinese face and not Helvetica.
3. Page 2 carries share capital; page 5 carries director details.
4. No value overflows its box or sits on a rule.
5. No empty grey field boxes painted over the values.

**This step is a real gate.** Every assertion in this block can pass while the
document looks wrong — that is exactly how the original defect shipped.

- [ ] **Step 2: Add the regression test that pins the fix**

```python
def test_the_document_renders_the_same_for_every_viewer():
    """The whole block in one assertion: no regeneration flag, an embedded
    face, and values that are page content rather than a viewer's guess."""
    pdf = _baked()
    reader = PdfReader(io.BytesIO(pdf))
    assert not reader.trailer["/Root"]["/AcroForm"].get("/NeedAppearances")
    assert len(reader.pages) == 9
    page_one = reader.pages[0].extract_text() or ""
    assert "Annual Return" in page_one
```

- [ ] **Step 3: Run everything**

```bash
cd backend && uv run pytest -q
cd ../frontend && npm run test
```

Expected: both suites green. Report the actual counts — do not claim green without the output in front of you.

- [ ] **Step 4: Clean up and commit**

```bash
rm -f nar1_check.pdf
git add backend/tests/test_nar1_form_appearance.py
git commit -m "test(nar1): pin the rendering fix against regression"
```

- [ ] **Step 5: Report**

State: both suite counts, the rendered page count, the document size, and
which of the five visual checks you confirmed by eye. If any check failed, say
which — a partial pass reported as a pass is worse than a failure.

---

## Self-Review Notes

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 defect — `NeedAppearances`, non-embedded `/PMingLiU` | 3 |
| §1 approach — baked layer, hidden widgets | 3 |
| §1 fonts — Tinos, Noto Serif TC, offline instancing, no runtime dep | 1 |
| §1 sizes — 10 / 14 / 12pt | 3 (`FIELD_SIZES`) |
| §1 tests — embedding, no PMingLiU, CJK, visual | 2, 3, 6 |
| §1b static nine-page form | 4 |
| §3 preview height | 5 |

**Deliberately deferred to their own blocks:** §2 email copy (Block D), §4
receipt upload (Block B), §5 self-approval (Block C), §6 drift gate (Block B),
§7 user creation (Block E).

**Known risk carried into execution:** Task 3 Step 6 and Task 4 Step 5 both
run the pre-existing `test_nar1_form_fill.py`. If either turns red, the change
has altered the *data* rather than only its rendering, and that is a stop —
not an assertion to update.
