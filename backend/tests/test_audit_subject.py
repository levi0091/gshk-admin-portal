"""The audit trail says WHICH module and WHICH record — services/audit_subject.

Levi 2026-09-04: "in a lot of actions it is not clear what case or company or
person it is referring to."
"""
import pytest

from services import audit_subject as sub


# --------------------------------------------------------------------------- #
#  The vocabularies are pinned, on BOTH sides of the wire.
#
#  These five strings go out as `filter=module:in:...` and land in a closed enum
#  in routers/audit.py. frontend/src/lib/auditVocabulary.test.js pins the same
#  literals, so a rename on either side fails CI rather than shipping a filter
#  option that matches nothing.
# --------------------------------------------------------------------------- #
def test_module_vocabulary_is_the_sidebar_names():
    assert sub.MODULES == (
        "post_incorporation", "body_corporate", "natural_person",
        "documents", "cr_filing",
    )


def test_every_module_has_a_label():
    assert [sub.MODULE_LABELS[m] for m in sub.MODULES] == [
        "Post-incorporation", "Body Corporate", "Natural Person",
        "Documents", "CR Filing",
    ]


def test_subject_kinds_are_pinned():
    assert sub.SUBJECT_KINDS == ("case", "company", "person")


# --------------------------------------------------------------------------- #
#  derive() — the fallback that classifies ~50 untouched call sites for free
# --------------------------------------------------------------------------- #
CASE_UUID = "11111111-2222-3333-4444-555555555555"
ENTITY_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_nar1_case_row_is_a_post_incorporation_case():
    out = sub.derive(entity_type="nar1_case", entity_id=CASE_UUID,
                     case_id=ENTITY_UUID)
    assert out["module"] == "post_incorporation"
    assert out["subject_kind"] == "case"
    # The CASE's own id, not the company's — a workflow row is about one filing.
    assert out["subject_id"] == CASE_UUID


def test_company_row_points_at_the_entity_in_case_id():
    out = sub.derive(entity_type="entity", entity_id=ENTITY_UUID,
                     case_id=ENTITY_UUID)
    assert out["module"] == "body_corporate"
    assert out["subject_kind"] == "company"
    assert out["subject_id"] == ENTITY_UUID


def test_share_class_and_record_location_are_still_the_company():
    for entity_type in ("share_class", "entity_record_location"):
        out = sub.derive(entity_type=entity_type, entity_id="anything",
                         case_id=ENTITY_UUID)
        assert out["module"] == "body_corporate", entity_type
        assert out["subject_id"] == ENTITY_UUID, entity_type


def test_person_row_points_at_the_person():
    out = sub.derive(entity_type="person", entity_id=CASE_UUID, case_id=None)
    assert out["module"] == "natural_person"
    assert out["subject_kind"] == "person"
    assert out["subject_id"] == CASE_UUID


def test_a_document_without_a_case_id_belongs_to_a_person():
    """The polymorphic guess. A company-owned document carries the entity in
    `case_id`; a person-owned one carries nothing there."""
    assert sub.derive(entity_type="document", entity_id="d", case_id=None
                      )["subject_kind"] == "person"
    assert sub.derive(entity_type="document", entity_id="d", case_id=ENTITY_UUID
                      )["subject_kind"] == "company"
    assert sub.derive(entity_type="document", entity_id="d", case_id=None
                      )["module"] == "documents"


def test_tpsi_events_are_cr_filing():
    for entity_type in ("tpsi", "tpsi_filing", "tpsi_credential"):
        out = sub.derive(entity_type=entity_type, entity_id="x", case_id=None)
        assert out["module"] == "cr_filing", entity_type


def test_the_shared_credential_never_writes_a_non_uuid_subject_id():
    """`entity_id` is TEXT and holds 'shared' for the firm's CR credential.
    `subject_id` is a uuid column; a bad value there fails the insert, and an
    audit write must never be the thing that breaks a save."""
    out = sub.derive(entity_type="tpsi_credential", entity_id="shared")
    assert "subject_id" not in out


def test_an_explicit_value_always_wins():
    out = sub.derive(
        entity_type="entity", case_id=ENTITY_UUID,
        module="documents", subject_kind="person", subject_id=CASE_UUID,
        subject_ref="A123456(7)",
    )
    assert out == {"module": "documents", "subject_kind": "person",
                   "subject_id": CASE_UUID, "subject_ref": "A123456(7)"}


def test_an_unknown_entity_type_says_nothing_rather_than_guessing_wrong():
    assert sub.derive(entity_type="something_new", entity_id="x") == {}


# --------------------------------------------------------------------------- #
#  The call-site helpers
# --------------------------------------------------------------------------- #
def test_for_company_quotes_the_brn():
    out = sub.for_company({"id": ENTITY_UUID, "company_name": "Kanenas Holding",
                           "br_number": "69123456"})
    assert out == {"module": "body_corporate", "subject_kind": "company",
                   "subject_id": ENTITY_UUID, "subject_ref": "69123456"}


def test_for_case_quotes_the_case_number():
    """The case number is the REFERENCE and the company is the name beside it —
    the cell reads "NAR1-2026-0042 (Kanenas Holding Limited)"."""
    out = sub.for_case({"id": CASE_UUID, "case_no": "NAR1-2026-0042"})
    assert out["subject_kind"] == "case"
    assert out["subject_id"] == CASE_UUID
    assert out["subject_ref"] == "NAR1-2026-0042"


def test_for_person_prefers_the_supplied_identity_number():
    out = sub.for_person({"id": CASE_UUID, "primary_id_number": "OLD"},
                         id_number="A123456(7)")
    assert out["subject_ref"] == "A123456(7)"


def test_helpers_take_a_module_override_for_documents():
    """A document on a company is a DOCUMENTS row about a COMPANY — the surface
    and the subject are different questions."""
    out = sub.for_company({"id": ENTITY_UUID}, module=sub.DOCUMENTS)
    assert out["module"] == "documents"
    assert out["subject_kind"] == "company"


def test_helpers_survive_a_missing_record():
    assert sub.for_company(None)["subject_id"] is None
    assert sub.for_person(None)["subject_kind"] == "person"


# --------------------------------------------------------------------------- #
#  primary_id_number — one query, and it never raises
# --------------------------------------------------------------------------- #
class _FakeSb:
    def __init__(self, data=None, boom=False):
        self.data, self.boom, self.ordered = data, boom, []

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a):
        return self

    def order(self, column, desc=False):
        self.ordered.append((column, desc))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self.boom:
            raise RuntimeError("supabase is down")
        return type("R", (), {"data": self.data})()


def test_primary_id_number_reads_the_primary_document_first():
    sb = _FakeSb([{"id_number": "A123456(7)"}])
    assert sub.primary_id_number(sb, CASE_UUID) == "A123456(7)"
    # Same order as person_registry's lateral join (migration 009), so the
    # trail quotes the document the registry screen shows.
    assert sb.ordered == [("is_primary", True), ("created_at", False)]


def test_primary_id_number_is_none_when_the_person_has_no_document():
    assert sub.primary_id_number(_FakeSb([]), CASE_UUID) is None


def test_primary_id_number_swallows_a_failure():
    """A missing reference makes a poorer trail, never a failed save."""
    assert sub.primary_id_number(_FakeSb(boom=True), CASE_UUID) is None


def test_primary_id_number_does_not_query_without_a_person():
    assert sub.primary_id_number(_FakeSb(boom=True), None) is None


@pytest.mark.parametrize("value,ok", [
    ("11111111-2222-3333-4444-555555555555", True),
    ("shared", False),
    ("ITUTORS", False),
    ("", False),
])
def test_uuid_shape_check(value, ok):
    assert sub._looks_like_uuid(value) is ok
