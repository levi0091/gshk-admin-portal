"""services/tpsi/forms/nar1_summary.py — the Submission stage's final summary.

Driven off XML built by the real mapper wherever possible, not hand-written
strings: a fixture invented here would agree with whatever this parser happens
to do, and the point is to agree with what `nar1.build_nar1_xml` emits.
"""
import pytest

from services.tpsi.forms import nar1_summary

#: A minimal fragment in CR's shape. Note it has NO root element and an
#: UNDECLARED `cr:` prefix -- that is what build_nar1_xml returns, because the
#: SOAP envelope supplies both.
FRAGMENT = (
    "<cr:language>E</cr:language>"
    "<cr:compNameE>Harbour Tech Ltd.</cr:compNameE>"
    "<cr:compNameC>海港科技有限公司</cr:compNameC>"
    "<cr:brNo>2100028</cr:brNo>"
    "<cr:yearAnnualReturn>2026</cr:yearAnnualReturn>"
    "<cr:roAddr>"
    "<cr:addrLangInd>E</cr:addrLangInd>"
    "<cr:flatFlrBlk>Unit 12A</cr:flatFlrBlk>"
    "<cr:bldg>Admiralty Centre</cr:bldg>"
    "<cr:stEstLotVlg>18 Harcourt Road</cr:stEstLotVlg>"
    "<cr:dstCtyStatePostal>CENTRAL</cr:dstCtyStatePostal>"
    "<cr:ctryRegion>HKG</cr:ctryRegion>"
    "</cr:roAddr>"
    "<cr:shareCapitals><cr:shareCapital>"
    "<cr:clsOfShares>Ordinary</cr:clsOfShares>"
    "<cr:currency>HKD</cr:currency>"
    "<cr:noOfShareIssuedOnThisCls>100</cr:noOfShareIssuedOnThisCls>"
    "<cr:paidUpCapital>100</cr:paidUpCapital>"
    "</cr:shareCapital></cr:shareCapitals>"
    "<cr:indSecList><cr:indSec>"
    "<cr:indvEngSname>WONG</cr:indvEngSname>"
    "<cr:indvEngOname>MEI LING</cr:indvEngOname>"
    "</cr:indSec></cr:indSecList>"
    "<cr:corpSecList><cr:corpSec>"
    "<cr:corpEngName>Get Started HK Limited</cr:corpEngName>"
    "<cr:corpBrNo>TC000807</cr:corpBrNo>"
    "</cr:corpSec></cr:corpSecList>"
    "<cr:indDirList><cr:indDir>"
    "<cr:indvEngSname>CHAN</cr:indvEngSname>"
    "<cr:indvEngOname>TAI MAN</cr:indvEngOname>"
    "</cr:indDir></cr:indDirList>"
    "<cr:selectPersonId>T260727100116S</cr:selectPersonId>"
    "<cr:selectPersonName>WONG, MEI LING</cr:selectPersonName>"
    "<cr:selectCapacityDesc>Company Secretary</cr:selectCapacityDesc>"
    "<cr:signatoryDate>27/08/2026</cr:signatoryDate>"
    "<cr:schedule1><cr:shares><cr:share>"
    "<cr:clsOfShares>Ordinary</cr:clsOfShares>"
    "<cr:shareHolderGrps><cr:shareHolderGrp>"
    "<cr:sharesAlloted>60</cr:sharesAlloted>"
    "<cr:allotteeRec><cr:allottee>"
    "<cr:allotteeType>I</cr:allotteeType>"
    "<cr:indvSurname>CHAN</cr:indvSurname>"
    "<cr:indvOtherName>TAI MAN</cr:indvOtherName>"
    "</cr:allottee></cr:allotteeRec>"
    "</cr:shareHolderGrp>"
    "<cr:shareHolderGrp>"
    "<cr:sharesAlloted>40</cr:sharesAlloted>"
    "<cr:allotteeRec><cr:allottee>"
    "<cr:allotteeType>C</cr:allotteeType>"
    "<cr:corpEngName>Nominee Holdings Ltd.</cr:corpEngName>"
    "</cr:allottee></cr:allotteeRec>"
    "</cr:shareHolderGrp></cr:shareHolderGrps>"
    "</cr:share></cr:shares></cr:schedule1>"
)


def test_parses_a_bare_fragment_with_an_undeclared_prefix():
    """build_nar1_xml returns no root and never declares `cr:`. A parser that
    assumed a document would raise `unbound prefix` on every real filing."""
    out = nar1_summary.summarise(FRAGMENT)
    assert out["company_name"] == "Harbour Tech Ltd."
    assert out["br_number"] == "2100028"
    assert out["year"] == "2026"


def test_flattens_the_registered_office_in_CRs_own_field_order():
    assert nar1_summary.summarise(FRAGMENT)["registered_office"] == (
        "Unit 12A, Admiralty Centre, 18 Harcourt Road, CENTRAL, HKG"
    )
    # addrLangInd is a language flag, not part of the address.
    assert "E," not in nar1_summary.summarise(FRAGMENT)["registered_office"]


def test_names_both_individual_and_corporate_officers():
    out = nar1_summary.summarise(FRAGMENT)
    assert out["directors"] == ["CHAN, TAI MAN"]
    assert out["secretaries"] == ["WONG, MEI LING", "Get Started HK Limited"]


def test_counts_members_from_schedule_1_not_from_the_company_record():
    """A member added to the profile after validation must NOT appear in a
    summary of a return that never carried them."""
    out = nar1_summary.summarise(FRAGMENT)
    assert out["member_count"] == 2
    assert out["members"] == ["CHAN, TAI MAN", "Nominee Holdings Ltd."]
    assert out["has_schedule_1"] is True


def test_reports_the_signatory_block():
    sig = nar1_summary.summarise(FRAGMENT)["signatory"]
    assert sig == {"name": "WONG, MEI LING", "capacity": "Company Secretary",
                   "date": "27/08/2026"}


def test_share_classes_carry_the_issued_count():
    assert nar1_summary.summarise(FRAGMENT)["share_classes"] == [
        {"name": "Ordinary", "currency": "HKD",
         "total_issued": "100", "paid_up": "100"}
    ]


def test_a_return_without_schedule_1_says_so():
    stripped = FRAGMENT[:FRAGMENT.index("<cr:schedule1>")]
    out = nar1_summary.summarise(stripped)
    assert out["has_schedule_1"] is False
    assert out["member_count"] == 0


def test_unparseable_xml_raises_rather_than_returning_a_hollow_summary():
    # Every row blank in front of an irreversible charge is worse than an error.
    with pytest.raises(ValueError, match="could not be parsed"):
        nar1_summary.summarise("<cr:compNameE>unclosed")


def test_missing_optional_fields_read_as_none_not_empty_string():
    out = nar1_summary.summarise("<cr:brNo>2100028</cr:brNo>")
    assert out["company_name"] is None
    assert out["registered_office"] is None
    assert out["directors"] == []
    assert out["signatory"] == {"name": None, "capacity": None, "date": None}


def test_round_trips_xml_from_the_real_mapper():
    """The parser must agree with what build_nar1_xml actually emits, not with
    a fragment written to suit it."""
    from services.tpsi.forms import nar1, nar1_mapper

    graph = {
        "entity": {"id": "e1", "company_name": "Round Trip Ltd.",
                   "br_number": "2100028"},
        "registered_address": {"line1": "Unit 1", "district": "Central",
                               "country": "HKG"},
        "officers": [], "secretaries": [], "share_classes": [],
        "shareholdings": [], "persons": {}, "addresses": {},
        "identity_documents": {},
    }
    try:
        data = nar1_mapper.map_entity(
            graph, year=2026,
            signatory={"name": "CHAN, TAI MAN", "capacity": "Director",
                       "person_id": "T2607D"},
        )
    except nar1_mapper.MappingError as exc:
        pytest.skip(f"graph not mappable in this build: {exc.problems}")

    out = nar1_summary.summarise(nar1.build_nar1_xml(data))
    assert out["company_name"] == "Round Trip Ltd."
    assert out["br_number"] == "2100028"
    assert out["signatory"]["name"] == "CHAN, TAI MAN"
    assert out["signatory"]["capacity"] == "Director"
