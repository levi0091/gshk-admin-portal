"""NAR1 schema tree (generated from CR's §7.2 worksheet, reconciled against
CR's shipped example instances)."""
import pathlib
from xml.etree import ElementTree as ET

import pytest

from services.tpsi.forms import spec

_EXAMPLES = sorted(
    (pathlib.Path(__file__).resolve().parents[3] / "docs" / "Web Form Example" / "validateForm")
    .glob("validate_NAR1*.xml")
)


def test_root_is_submission_with_eform_beneath():
    root = spec.load_nar1_schema()
    assert root.name == "submission"
    assert any(c.name == "EForm" for c in root.children)


def test_eform_is_capital_F_as_cr_actually_sends_it():
    """CR's worksheet spells it 'Eform'; every shipped example says 'EForm'.
    The examples win — the generator reconciles this deliberately."""
    assert spec.find("EForm") is not None
    assert spec.find("Eform") is None


def test_scalar_path_resolves():
    node = spec.find("EForm/formModel/formCode")
    assert node is not None
    assert node.children == []


def test_nested_address_is_a_container_not_a_scalar():
    """roAddr holds addrLangInd/bldg/... — a flat builder would emit it wrong."""
    node = spec.find("EForm/formModel/roAddr")
    assert node is not None
    assert {c.name for c in node.children} >= {"bldg", "ctryRegion", "flatFlrBlk"}


def test_repeating_containers_are_identified():
    """shareCapitals/shareCapital and indSecList/indSec repeat; the builder must
    emit one child element per input item rather than a single element."""
    repeating = spec.repeating_containers()
    assert "EForm/formModel/shareCapitals" in repeating
    assert "EForm/formModel/indSecList" in repeating


def test_share_level_is_interposed_under_shares():
    """The worksheet flattens schedule1/shares/share away, but CR's examples
    nest clsOfShares inside a repeating <share>. Without this the builder could
    not represent more than one share class."""
    assert spec.find("EForm/formModel/schedule1/shares/share/clsOfShares") is not None
    assert "EForm/formModel/schedule1/shares" in spec.repeating_containers()


def test_individual_tcsp_number_uses_the_xml_spelling():
    """Worksheet says 'tcspNo' inside indSec; the examples say 'indvTcspNo'.
    The corporate sibling is 'corpTcspNo' in both."""
    assert spec.find("EForm/formModel/indSecList/indSec/indvTcspNo") is not None
    assert spec.find("EForm/formModel/corpSecList/corpSec/corpTcspNo") is not None


def test_max_length_and_mandatory_are_exposed():
    node = spec.find("EForm/formModel/brNo")
    assert node.max_length and node.max_length > 0
    assert isinstance(node.mandatory, bool)


def test_webui_field_names_are_absent():
    """S2compName et al. come from NAR1_Data_Specification.v1.4.xls, which
    describes the web UI and appears in no XML CR ships."""
    for name in ("S2compName", "formMode", "AccBarcode", "S11Aname"):
        assert spec.find(f"EForm/formModel/{name}") is None


def test_unknown_path_returns_none():
    assert spec.find("EForm/formModel/definitelyNotAField") is None


def test_load_is_cached():
    assert spec.load_nar1_schema() is spec.load_nar1_schema()


@pytest.mark.parametrize("path", _EXAMPLES, ids=lambda p: p.name)
def test_schema_covers_every_element_cr_actually_sends(path):
    """The gate that matters: an element missing from the schema is an element
    the builder can never emit, and the omission would only surface as an opaque
    CR rejection."""
    names: set[str] = set()

    def collect(node):
        for child in node.children:
            names.add(child.name)
            collect(child)

    collect(spec.load_nar1_schema())

    doc = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    used = {e.tag.rsplit("}", 1)[-1] for e in doc.iter()}
    structural = {"Envelope", "Body", "validateForm", "submission"}
    assert not sorted((used - names) - structural)
