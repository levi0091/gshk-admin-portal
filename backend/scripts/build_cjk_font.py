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
        static = instancer.instantiateVariableFont(font, {"wght": WEIGHT}, updateFontNames=True)
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        static.save(TARGET)
    finally:
        cache.unlink(missing_ok=True)
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes) at wght={WEIGHT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
