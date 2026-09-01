# Fonts for the generated NAR1

Committed here, **not** in `docs/`, which is gitignored repo-wide: a font that
lives there is present on one laptop and absent from CI, Railway, and every
fresh clone. These are runtime assets, exactly like `form/NAR1_fillable.pdf`.

| File | Family | Licence | Source |
|---|---|---|---|
| `Tinos-Bold.ttf` | Tinos Bold | OFL-1.1 | github.com/googlefonts/Tinos |
| `Tinos-Regular.ttf` | Tinos Regular | OFL-1.1 | github.com/googlefonts/Tinos |
| `NotoSerifTC-Bold.ttf` | Noto Serif TC | OFL-1.1 | Built by `scripts/build_cjk_font.py` |

## Why Tinos and not Times New Roman

CR's own returns fill values in Times New Roman Bold. Times New Roman is
Monotype-proprietary and cannot be redistributed in this repo or a Railway image.
Tinos is **metrically identical** to it: measured across company names,
addresses, amounts and email addresses, the advance-width delta at 10pt is
exactly 0.0000pt. Nothing wraps or overflows differently. Tinos is OFL-1.1
licensed and therefore freely redistributable.

**OFL-1.1 Reserved Font Name**: The OFL-1.1 licence requires that the font files
keep their names and must not be modified and redistributed under the same name.
The CJK font **is** modified by `build_cjk_font.py` to instance it to `wght=700`,
but the output file keeps the upstream family name and is used internally by the
application rather than redistributed as a font, so this is permitted.

## Regenerating the CJK face

    uv run --with fonttools --with brotli python scripts/build_cjk_font.py

Noto Serif TC publishes a variable font whose **default instance is
ExtraLight**, and no static TrueType Bold. The script instances it to
`wght=700`. Do not swap in the `SubsetOTF` build: reportlab cannot read
PostScript outlines and raises `TTFError` on it.
