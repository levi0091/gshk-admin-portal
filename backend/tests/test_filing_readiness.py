"""Whether a company can produce a valid return, computed before a case opens.

PRD OQ-2: Levi chose to BLOCK rather than warn. Measured against DEV, that
stops 453 of 5,930 client companies (7.6%) -- 252 with no registered-office
country, 219 with no share class, 18 in both. Every one of those genuinely
cannot produce a NAR1, so the block converts a failure discovered at CR, after
a chargeable and irreversible submit, into one visible on the profile.

Only fields CR marks Mandatory=Y can block. Business nature is M=N on both
forms and must never appear here, however empty it is.
"""
from services.cr_forms.readiness import filing_problems


def _company(**overrides):
    company = {
        "registered_address": {"line1": "Unit 1", "country": "HKG"},
        "share_classes": [{
            "class_name": "Ordinary", "currency": "HKD",
            "total_issued": 10000, "issued_amount": 10000, "total_paid": 10000,
        }],
        "business_nature_code": None,
    }
    company.update(overrides)
    return company


def test_a_complete_company_has_no_problems():
    assert filing_problems(_company()) == []


def test_business_nature_never_blocks_however_empty():
    """CR marks it M=N on NAR1 (`nature`) and NNC1 (`bnCode`), and Viewpoint
    has none for any of the 5,028 rows, so blocking on it would freeze the
    whole book over a field CR does not require."""
    assert filing_problems(_company(business_nature_code=None)) == []


def test_a_missing_registered_office_country_blocks():
    problems = filing_problems(_company(registered_address=None))

    assert len(problems) == 1
    assert "registered office" in problems[0]["message"].lower()
    assert problems[0]["field"] == "registered_address.country"


def test_a_registered_office_without_a_country_blocks():
    problems = filing_problems(
        _company(registered_address={"line1": "Unit 1", "country": ""}))

    assert [p["field"] for p in problems] == ["registered_address.country"]


def test_no_share_class_blocks():
    """219 client companies are in this state -- and Viewpoint has no share
    capital for them either, so it is theirs to fix, not the ETL's."""
    problems = filing_problems(_company(share_classes=[]))

    assert [p["field"] for p in problems] == ["share_classes"]


def test_an_incomplete_share_class_blocks_and_names_the_column():
    problems = filing_problems(_company(share_classes=[{
        "class_name": "Ordinary", "currency": "HKD",
        "total_issued": 10000, "issued_amount": None, "total_paid": 10000,
    }]))

    assert [p["field"] for p in problems] == ["share_classes.issued_amount"]


def test_problems_accumulate_rather_than_stopping_at_the_first():
    """An operator fixing one thing at a time, told only about the next
    failure each time, is the worst version of this."""
    problems = filing_problems(
        _company(registered_address=None, share_classes=[]))

    assert {p["field"] for p in problems} == {
        "registered_address.country", "share_classes"}
