# Fonts for the generated NAR1

Committed here, **not** in `docs/`, which is gitignored repo-wide: a font that
lives there is present on one laptop and absent from CI, Railway, and every
fresh clone. These are runtime assets, exactly like `form/NAR1_fillable.pdf`.

| File | Family | Licence | Source |
|---|---|---|---|
| `Tinos-Bold.ttf` | Tinos Bold | OFL-1.1 | github.com/googlefonts/Tinos |
| `Tinos-Regular.ttf` | Tinos Regular | OFL-1.1 | github.com/googlefonts/Tinos |
| `NotoSerifTC-Bold.ttf` | Noto Serif TC | OFL-1.1 | Built by `scripts/build_cjk_font.py` |
| `NotoSerifSC-Bold.ttf` | Noto Serif SC | OFL-1.1 | Built by `scripts/build_cjk_font.py` |

`OFL.txt`, beside these files, is the licence text itself -- OFL-1.1 asks
for it to travel with the fonts, not just be linked to from here.

## Why Tinos and not Times New Roman

CR's own returns fill values in Times New Roman Bold. Times New Roman is
Monotype-proprietary and cannot be redistributed in this repo or a Railway image.
Tinos is **metrically identical** to it: measured across company names,
addresses, amounts and email addresses, the advance-width delta at 10pt is
exactly 0.0000pt. Nothing wraps or overflows differently. Tinos is OFL-1.1
licensed and therefore freely redistributable.

**OFL-1.1 Reserved Font Name**: neither family reserves one. A Reserved Font
Name is whatever the copyright holder names explicitly in the licence text
that ships with the font (OFL-1.1 §"Definitions"); it is not automatic, and
absent one, condition 3 (no modified version may use the Reserved Font
Name(s)) has nothing to bind. Checked directly against what each file itself
declares (`name` table, nameID 13/14, read with `fontTools`) rather than
assumed: Tinos' is the licence's plain FAQ-pointer text with no name
singled out, and Noto Serif TC's the same. So instancing the CJK font to
`wght=700` in `build_cjk_font.py` needs no permission this licence would
otherwise withhold -- there is no reserved name to have collided with by
keeping the upstream family name on the output file.

## Regenerating the CJK face

    uv run --with fonttools --with brotli python scripts/build_cjk_font.py

Noto Serif TC publishes a variable font whose **default instance is
ExtraLight**, and no static TrueType Bold. The script instances it to
`wght=700`. Do not swap in the `SubsetOTF` build: reportlab cannot read
PostScript outlines and raises `TTFError` on it.

**Coverage.** This is the `Serif/Variable/TTF/Subset/NotoSerifTC-VF.ttf`
build -- 20,748 codepoints, curated for Traditional Chinese use, not full CJK
Unified coverage. A few real DEV names (measured 2026-09-01: U+6768, U+59D7,
U+3F18) have no glyph in it; `appearance.draw_value` raises `AppearanceError`
for those rather than drawing nothing, so this is loud, not silent. The
non-Subset per-region build, `Serif/Variable/TTF/NotoSerifCJKtc-VF.ttf`, DOES
cover those three -- but instances to ~34MB (measured), over this repo's
25MB stop line, and was ALSO measured to carry zero CJK Extension B
codepoints where this Subset build carries 1,705. Do not swap it in as a
quick fix for one gap; it trades that gap for a different, bigger one at
3.4x the size. See
`.superpowers/sdd/2026-09-01-block-a-nar1-form-fidelity/final-fix-report.md`
for the numbers.

## Why BOTH a Traditional and a Simplified CJK face

Hong Kong's register is Traditional, so `appearance._CJK_FACES` tries Noto
Serif **TC** first and falls back to **SC** only for characters TC cannot draw.
Preferring TC matters: a name both faces cover would otherwise render in
Simplified shapes on a Hong Kong statutory return.

SC is not optional. Measured against DEV, three rows across
`persons.full_name_zh` and `entities.company_name_zh` carry characters Noto
Serif TC has no glyph for -- among them **U+6768 杨**, the simplified form of a
top-ten Hong Kong surname. Mainland directors of Hong Kong companies are
ordinary, and their names arrive in Simplified. TC is not redundant either: it
carries roughly 1,700 codepoints SC does not.

Neither face is a general fallback: a character *neither* covers is refused by
name in `appearance.draw_value` rather than drawn as nothing. reportlab maps an
uncovered codepoint to glyph 0 and draws blank without raising, which is how a
missing character in a director's name went unnoticed in the first place.
