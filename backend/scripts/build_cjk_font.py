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

#: STILL the Subset build, NOT `Serif/Variable/TTF/NotoSerifCJKtc-VF.ttf` --
#: evaluated 2026-09-02 and deliberately not switched. That "full" per-region
#: build was fetched, instanced and measured: 35,542,216 bytes (~33.9MB) at
#: wght=700, over the >25MB stop line the fidelity review set. Measuring its
#: cmap turned up a second problem the review did not anticipate: it covers
#: the BMP gaps this Subset build misses (U+6768, U+59D7, U+3F18 -- none of
#: which round-trip through the CURRENT font either, see AppearanceError) but
#: carries ZERO CJK Extension B codepoints, where the CURRENT Subset build
#: (still shipped below) carries 1,705. Swapping would trade one silent gap
#: for a different one at 3.4x the size, not close it. Left for the
#: controller -- see 2026-09-01-block-a-nar1-form-fidelity/final-fix-report.md
#: for the full numbers. `appearance.draw_value` now REFUSES to draw a
#: character the selected face cannot show rather than blanking it, so this
#: gap is loud (`AppearanceError`) rather than invisible either way.
#: The two CJK faces, in the order `appearance._CJK_FACES` tries them.
#: BOTH are needed. Hong Kong's register is Traditional, but mainland directors
#: of Hong Kong companies are ordinary and their names arrive in Simplified --
#: measured on DEV, 3 rows across `persons.full_name_zh` and
#: `entities.company_name_zh` carry characters Noto Serif TC has no glyph for,
#: including U+6768 杨, the simplified form of a top-ten HK surname. TC is not
#: redundant either: it carries ~1,700 codepoints SC does not.
_BASE = ("https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
         "Serif/Variable/TTF/Subset/")
FACES = {
    "NotoSerifTC-Bold.ttf": _BASE + "NotoSerifTC-VF.ttf",
    "NotoSerifSC-Bold.ttf": _BASE + "NotoSerifSC-VF.ttf",
}
FONT_DIR = Path(__file__).resolve().parents[1] / "services" / "nar1_form" / "fonts"
WEIGHT = 700


def main() -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, source in FACES.items():
        target = FONT_DIR / filename
        print(f"downloading {source}")
        raw = urllib.request.urlopen(source, timeout=300).read()
        cache = FONT_DIR / ("_" + filename)
        cache.write_bytes(raw)
        try:
            # updateFontNames=True, or the instanced file keeps the VARIABLE
            # default's name -- ExtraLight -- and every PDF embeds a font
            # announcing a weight it is not.
            static = instancer.instantiateVariableFont(
                TTFont(cache), {"wght": WEIGHT}, updateFontNames=True)
            static.save(target)
        finally:
            cache.unlink(missing_ok=True)
        print(f"wrote {target} ({target.stat().st_size} bytes) at wght={WEIGHT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
