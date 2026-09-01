"""The CR form contract — every NAR1/NNC1 field accounted for.

WHY. The Company and Person profiles were built as a records system; NAR1 and
NNC1 are filing systems. A field CR requires that no profile column holds is
invisible until a filing fails, and a filing fails at CR — after a chargeable,
irreversible submission. These tests make an unaccounted-for field a red test
instead.

The authority is CR's own worksheet, committed at
`tests/fixtures/cr-examples/Worksheet in TPSI API Interface v1.0.14.xlsx`. It
ranks above the API .docx per the standing rule (CR's shipped XML > the
worksheet > the .docx, whose embedded examples are wrong).
"""
import pytest

from services.cr_forms import contract, worksheet

#: The forms this PRD reconciles the profiles against. NNC1G (guarantee
#: companies) is deliberately absent: it is R3 scope and adding it here would
#: fail the coverage test for fields nobody has agreed to hold yet.
RECONCILED_FORMS = ("NAR1", "NNC1")


def _all_fields():
    return [f for form in RECONCILED_FORMS for f in worksheet.load_fields(form)]


def test_loads_a_known_optional_field_with_its_cr_length():
    """`indvEngOname` is NAR1's "Other Names" — the field Brian asked us to
    rename "Given Names" to. CR gives it 110 characters and does not require
    it; both facts have to survive the parse or the contract is decorative."""
    fields = {f.name: f for f in worksheet.load_fields("NAR1")}

    other_names = fields["indvEngOname"]

    assert other_names.max_length == 110
    assert other_names.mandatory is False
    assert "Other Names" in other_names.remark


def test_every_field_on_both_forms_has_a_disposition():
    """The point of the contract. A CR field with no disposition is one nobody
    decided about, and the failure mode for an undecided field is a rejected
    filing after a chargeable, irreversible submit. Adding a field to CR's
    worksheet must therefore break this test until someone rules on it."""
    undecided = sorted(
        f"{f.form} {f.path}"
        for f in _all_fields()
        if contract.disposition_for(f.form, f.path) is None
    )

    assert not undecided, (
        f"{len(undecided)} CR field(s) have no disposition:\n  "
        + "\n  ".join(undecided[:25])
    )


def test_contract_holds_no_field_cr_no_longer_has():
    """Drift in the other direction. A stale entry is how a contract starts
    describing a form CR has already changed — it keeps the coverage test
    green while quietly asserting a field that no longer exists."""
    current = {(f.form, f.path) for f in _all_fields()}

    stale = sorted(f"{form} {path}" for form, path in contract.FIELDS
                   if (form, path) not in current)

    assert not stale, (
        f"{len(stale)} contract entry/entries are not in CR's worksheet; "
        f"regenerate with scripts/build_cr_form_contract.py:\n  "
        + "\n  ".join(stale[:25])
    )


def test_every_disposition_carries_a_target_or_a_reason():
    """`unsourced` and `form_instance` are the two ways to say "not built".
    Both are only defensible with a stated reason — otherwise an omission
    someone decided on is indistinguishable from one nobody noticed."""
    silent = sorted(
        f"{form} {path} ({entry[0]})"
        for (form, path), entry in contract.FIELDS.items()
        if not (entry[1] or "").strip()
    )

    assert not silent, (
        f"{len(silent)} entry/entries state no target or reason:\n  "
        + "\n  ".join(silent[:25])
    )
