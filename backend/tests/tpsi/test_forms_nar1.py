"""NAR1 nested XML builder + validation."""
import pathlib
from xml.etree import ElementTree as ET

import pytest

from services.tpsi.forms import nar1

BASE = {
    "formCode": "NAR1",
    "language": "E",
    "brNo": "00000001",
    "compNameE": "TEST COMPANY LIMITED",
    "dateReturnMadeUp": "31/10/2020",
    "yearAnnualReturn": "2020",
}

_EXAMPLE_DIR = (
    pathlib.Path(__file__).resolve().parents[3] / "docs" / "Web Form Example" / "validateForm"
)


def test_scalars_are_cr_prefixed():
    xml = nar1.build_nar1_xml(BASE)
    assert "<cr:formCode>NAR1</cr:formCode>" in xml
    assert "<cr:brNo>00000001</cr:brNo>" in xml
    assert "<formCode>" not in xml  # never unprefixed


def test_nested_container_is_emitted_as_a_container():
    xml = nar1.build_nar1_xml(
        {**BASE, "roAddr": {"addrLangInd": "E", "bldg": "Building", "ctryRegion": "HKG"}}
    )
    assert "<cr:roAddr>" in xml
    assert "<cr:bldg>Building</cr:bldg>" in xml
    assert xml.index("<cr:roAddr>") < xml.index("<cr:bldg>") < xml.index("</cr:roAddr>")


def test_repeating_list_emits_one_child_per_item():
    """A flat builder would emit shareCapitals once and lose the second class."""
    xml = nar1.build_nar1_xml(
        {
            **BASE,
            "shareCapitals": [
                {"clsOfShares": "Share Capital A", "currency": "HKD"},
                {"clsOfShares": "Share Capital B", "currency": "CAD"},
            ],
        }
    )
    assert xml.count("<cr:shareCapital>") == 2
    assert xml.count("<cr:shareCapitals>") == 1
    assert "Share Capital A" in xml and "Share Capital B" in xml


def test_empty_repeating_list_omits_the_container():
    xml = nar1.build_nar1_xml({**BASE, "shareCapitals": []})
    assert "shareCapitals" not in xml


def test_deep_schedule1_nesting_round_trips():
    """The deepest NAR1 nesting, and the level CR's worksheet omits entirely."""
    xml = nar1.build_nar1_xml(
        {
            **BASE,
            "schedule1": {
                "shares": [
                    {
                        "clsOfShares": "Share Capital A",
                        "shareHolderGrps": [{"sharesAlloted": "100", "shType": "1"}],
                    }
                ]
            },
        }
    )
    assert "<cr:schedule1>" in xml
    assert "<cr:share>" in xml
    assert "<cr:shareHolderGrp>" in xml
    assert "<cr:sharesAlloted>100</cr:sharesAlloted>" in xml


def test_ampersand_is_escaped():
    """CR 'Important Notes': & must be escaped to &amp; in the XML."""
    xml = nar1.build_nar1_xml({**BASE, "compNameE": "SMITH & JONES LIMITED"})
    assert "SMITH &amp; JONES LIMITED" in xml
    assert "SMITH & JONES" not in xml


def test_angle_brackets_are_escaped():
    xml = nar1.build_nar1_xml({**BASE, "compNameE": "<A>"})
    assert "&lt;A&gt;" in xml


def test_control_characters_are_rejected():
    """CR: no control characters, including Tab."""
    errors = nar1.validate({**BASE, "compNameE": "TEST\tCO"})
    assert any("control character" in e for e in errors)


def test_max_length_counts_characters_not_bytes():
    """CR counts CHARACTERS. 100 Chinese chars is 300 UTF-8 bytes; a byte-based
    check would reject a legal value."""
    node = nar1.SCHEMA_FIND("EForm/formModel/compNameC")
    assert node.max_length, "compNameC should carry a max length"
    assert nar1.validate({**BASE, "compNameC": "山" * node.max_length}) == []
    assert nar1.validate({**BASE, "compNameC": "山" * (node.max_length + 1)})


def test_unknown_field_is_rejected_rather_than_silently_dropped():
    """A typo'd key must not vanish — the form would go short a value with no
    error anywhere."""
    errors = nar1.validate({**BASE, "notARealField": "x"})
    assert any("notARealField" in e for e in errors)


def test_webui_field_names_are_rejected():
    """S2compName/formMode/AccBarcode come from the web-UI spreadsheet and are
    not XML elements. Accepting them silently would build a form CR rejects."""
    errors = nar1.validate({**BASE, "S2compName": "X", "formMode": "T"})
    assert any("S2compName" in e for e in errors)
    assert any("formMode" in e for e in errors)


def test_scalar_given_a_dict_is_reported():
    errors = nar1.validate({**BASE, "brNo": {"nested": "wrong"}})
    assert any("brNo" in e for e in errors)


def test_container_given_a_scalar_is_reported():
    errors = nar1.validate({**BASE, "roAddr": "just a string"})
    assert any("roAddr" in e for e in errors)


def test_every_error_is_reported_not_just_the_first():
    """Same reason CR returns a full fault list: one round trip per field is
    unusable."""
    errors = nar1.validate({"nope1": "a", "nope2": "b", "nope3": "c"})
    assert len(errors) >= 3


def test_empty_values_are_omitted():
    xml = nar1.build_nar1_xml({**BASE, "telNo": ""})
    assert "telNo" not in xml


def test_element_order_follows_the_schema_not_dict_order():
    """Deterministic output — dict-order dependence would give CR a different
    document, and therefore a different digest, run to run."""
    a = nar1.build_nar1_xml(BASE)
    b = nar1.build_nar1_xml(dict(reversed(list(BASE.items()))))
    assert a == b


def test_build_raises_when_validation_fails():
    with pytest.raises(ValueError):
        nar1.build_nar1_xml({"notARealField": "x"})


def test_na_word_set_is_case_insensitive():
    assert nar1.is_na_value("n.a.")
    assert nar1.is_na_value("N.A.")
    assert nar1.is_na_value("not applicable")


def test_NA_is_not_an_na_value_for_english_names():
    """CR: the English-name N.A. set EXCLUDES bare 'NA' — it can be a real name
    fragment."""
    assert nar1.is_na_value("NA") is True
    assert nar1.is_na_value("NA", english_name=True) is False


def _to_dict(el):
    """Turn a CR formModel element into the builder's nested-dict input.

    Uses the same wrapper rule as the schema (a wrapper's name extends its
    repeated child's name) rather than guessing from structure — guessing on
    "one child that itself has children" misreads `schedule1`, whose only child
    is `shares`.
    """
    def local(t):
        return t.rsplit("}", 1)[-1]

    out = {}
    for child in el:
        name = local(child.tag)
        kids = list(child)
        kid_names = {local(k.tag) for k in kids}
        if kids and len(kid_names) == 1 and name.startswith(next(iter(kid_names))):
            out[name] = [_to_dict(k) for k in kids]
        elif kids:
            out[name] = _to_dict(child)
        else:
            out[name] = (child.text or "").strip()
    return out


@pytest.mark.parametrize(
    "path", sorted(_EXAMPLE_DIR.glob("validate_NAR1*.xml")), ids=lambda p: p.name
)
def test_round_trips_crs_own_nar1_instance(path):
    """The decisive test: parse CR's real NAR1 into the builder's input shape,
    rebuild it, and confirm every element carrying a value comes back.

    Catches a builder that is individually plausible but collectively wrong —
    a wrong nesting level, a repeating list emitted once, a dropped subtree.

    Compared on NON-EMPTY elements only. CR's instances include empty
    placeholder tags (`<cr:docReferenceNo/>`, `<cr:indvTcspNo/>`, …) for
    optional fields; the builder deliberately omits empties, on the basis that
    CR treats an absent and a blank element alike. That assumption is only
    settled by a live validateForm call, and if CR turns out to want the
    placeholders it is a one-line change in `_build_level`.
    """
    def local(t):
        return t.rsplit("}", 1)[-1]

    def named_with_values(el):
        return {
            local(e.tag)
            for e in el.iter()
            if list(e) or (e.text or "").strip()
        }

    doc = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    form_model = next(e for e in doc.iter() if local(e.tag) == "formModel")

    data = _to_dict(form_model)
    assert nar1.validate(data) == []

    built = ET.fromstring(
        '<cr:formModel xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">'
        + nar1.build_nar1_xml(data)
        + "</cr:formModel>"
    )
    assert named_with_values(form_model) == named_with_values(built)


@pytest.mark.parametrize(
    "path", sorted(_EXAMPLE_DIR.glob("validate_NAR1*.xml")), ids=lambda p: p.name
)
def test_repeating_lists_keep_their_cardinality(path):
    """Element *names* matching is not enough — a builder that emitted one
    `indSec` where CR sent three would still pass a name-set comparison."""
    def local(t):
        return t.rsplit("}", 1)[-1]

    doc = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    form_model = next(e for e in doc.iter() if local(e.tag) == "formModel")
    data = _to_dict(form_model)

    built = ET.fromstring(
        '<cr:formModel xmlns:cr="http://interfaces.service.webservice.icris3e.cr.gov.hk/">'
        + nar1.build_nar1_xml(data)
        + "</cr:formModel>"
    )

    for item in ("shareCapital", "indSec", "corpSec", "indDir", "corpDir", "share",
                 "shareHolderGrp", "allottee"):
        expected = sum(1 for e in form_model.iter() if local(e.tag) == item)
        actual = sum(1 for e in built.iter() if local(e.tag) == item)
        assert actual == expected, f"{item}: expected {expected}, built {actual}"
