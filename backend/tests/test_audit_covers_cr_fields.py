"""Every profile column CR depends on must be named in the audit trail.

`company_field_code` / `person_field_code` fall back to a default rather than
raising, so a column missing from the maps does not fail — it writes an audit
row filed under the wrong Viewpoint folder, and nobody finds out. That is the
same failure CLAUDE.md records for unseeded `audit_event_types`: it "writes
fine and then renders unlabelled in the trail".

The CR contract already knows exactly which columns matter, so this ties the
two together: a column the forms depend on that nobody taught the audit trail
about is a red test.
"""
from services.audit_events import _COMPANY_FIELD_CODES, _PERSON_FIELD_CODES
from services.cr_forms import contract

#: Columns written by something other than a profile field edit, so they never
#: produce a CASE_FIELD_UPDATED / PERSON_FIELD_UPDATED row.
#:
#: `registered_address_id` and `residential_address_id` ARE audited, but as
#: address events (VP_REG_OFFICE) from the address endpoints rather than as
#: field edits — they appear in the maps already and are not exempt here.
NOT_FIELD_EDITS = {
    # Identity documents, contacts, share classes, shareholdings, officers and
    # record locations are child rows with their own endpoints and their own
    # audit codes (PARTY_*, GF_DOC_*), not columns on entities/persons.
    "person_identity_documents", "contacts", "share_classes", "shareholdings",
    "entity_officers", "business_names", "addresses", "entity_record_locations",
}


def _mapped_columns(table: str) -> set[str]:
    columns = set()
    for entry in contract.FIELDS.values():
        if entry[0] != "mapped":
            continue
        target = entry[1]
        if "." not in target:
            continue
        owner, column = target.split(".", 1)
        if owner == table:
            columns.add(column)
    return columns


def test_every_cr_mapped_entities_column_has_an_audit_field_code():
    missing = sorted(_mapped_columns("entities") - set(_COMPANY_FIELD_CODES))

    assert not missing, (
        "entities column(s) the CR forms depend on with no explicit audit "
        f"code, so edits file under the fallback folder: {missing}"
    )


def test_every_cr_mapped_persons_column_has_an_audit_field_code():
    missing = sorted(_mapped_columns("persons") - set(_PERSON_FIELD_CODES))

    assert not missing, (
        "persons column(s) the CR forms depend on with no explicit audit "
        f"code, so edits file under the fallback folder: {missing}"
    )
