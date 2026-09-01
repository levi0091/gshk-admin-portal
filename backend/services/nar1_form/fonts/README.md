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
