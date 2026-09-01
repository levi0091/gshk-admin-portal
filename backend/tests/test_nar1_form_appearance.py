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
