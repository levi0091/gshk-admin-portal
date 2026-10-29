"""Multi-director signing: the signer state machine (nd2-multi-signer, spec 2.3,
2.7 and test groups 3 to 5), plus the pins that keep NAR1 on its own path.

`FakeSupabase` serves everything that is a plain table query. `latest_sends`
filters on JSON paths (`metadata->>template`), which the fake does not model, so
it is tested against a MagicMock query chain that records what it was asked.
No test reaches Supabase, Resend or DNS.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from jobs import auto_approve_nar1 as job
from services import nar1_approvals, nar1_cases
from services.officer_changes import cases, signatures, signers
from tests.officer_changes.fakes import FakeSupabase

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=5)

KOH = {"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]}
BRIAN = {"person_id": "P2", "name": "Testing Brian", "roles": ["consent", "resolution"]}
FROZEN = [KOH, BRIAN]


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "nar1_cases": [{"id": "C1", "entity_id": "E1", "form_code": "Nd2a",
                        "multi_signer": True, "client_approved": None,
                        "closed_at": None,
                        "verification_sent_at": NOW.isoformat(),
                        "verification_revision": 1}],
        "nar1_client_approvals": [],
        "officer_change_signatures": [],
        "persons": [{"id": "P1", "email": "jkoh@client.com"},
                    {"id": "P2", "email": None}],
        "contacts": [],
    })
    for module in (signers, signatures, cases, nar1_approvals, nar1_cases):
        monkeypatch.setattr(module, "get_supabase", lambda: fake)
    return fake


def _case(**over):
    return {"id": "C1", "entity_id": "E1", "form_code": "Nd2a", "multi_signer": True,
            "verification_sent_at": NOW.isoformat(), "verification_revision": 1,
            "required_signers": FROZEN, "client_approved": None, **over}


def _row(db, person, *, outcome=None, revision=1, email=None, sent="2026-10-29T08:00:00+00:00",
         expires=None, responded=None, rid=None):
    row = {"id": rid or f"A-{person}-{len(db.tables['nar1_client_approvals'])}",
           "nar1_case_id": "C1", "person_id": person,
           "recipient_email": email or f"{person.lower()}@client.com",
           "recipient_name": {"P1": "Jacqueline Koh", "P2": "Testing Brian"}.get(person),
           "outcome": outcome, "revision": revision, "sent_at": sent,
           "expires_at": expires or FUTURE.isoformat(), "responded_at": responded}
    db.tables["nar1_client_approvals"].append(row)
    return row


def _sig(db, person, revision=1):
    db.tables["officer_change_signatures"].append(
        {"id": f"S-{person}-{revision}", "case_id": "C1", "person_id": person,
         "revision": revision, "approval_id": f"A-{person}"})


def _signed(db, person, responded, **kw):
    return _row(db, person, outcome="approved", responded=responded, **kw)


# -- the round and its set ---------------------------------------------------------

def test_a_round_is_open_once_something_was_sent():
    assert signers.round_open(_case()) is True
    assert signers.round_open(_case(verification_sent_at=None)) is False


def test_the_frozen_set_governs_an_open_round(monkeypatch):
    monkeypatch.setattr(signatures, "required_signers",
                        lambda c: pytest.fail("a frozen round must not read the live set"))
    assert signers.signer_set(_case()) == (FROZEN, True)


def test_before_the_round_opens_the_live_set_is_used(monkeypatch):
    monkeypatch.setattr(signatures, "required_signers", lambda c: [KOH])
    assert signers.signer_set(_case(verification_sent_at=None,
                                    required_signers=None)) == ([KOH], False)


def test_an_open_round_with_no_frozen_set_falls_back_to_the_live_one(monkeypatch):
    monkeypatch.setattr(signatures, "required_signers", lambda c: [KOH])
    assert signers.signer_set(_case(required_signers=None)) == ([KOH], False)


def test_freeze_stores_plain_json_in_order():
    extra = {**KOH, "email": "leak@x", "junk": 1}
    assert signers.freeze([BRIAN, extra]) == [
        {"person_id": "P2", "name": "Testing Brian", "roles": ["consent", "resolution"]},
        {"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]},
    ]


def test_round_approvals_reads_the_current_revision_only(db):
    _row(db, "P1", revision=1)
    _row(db, "P1", revision=2)
    got = signers.round_approvals(_case(verification_revision=2))
    assert [r["revision"] for r in got] == [2]


def test_round_approvals_is_empty_before_any_send(db):
    _row(db, "P1", revision=1)
    assert signers.round_approvals(_case(verification_revision=0)) == []


# -- state: the six-status contract, four of them here ------------------------------

def _by_person(report):
    return {s["person_id"]: s for s in report["signers"]}


def test_nobody_has_been_sent_anything(db, monkeypatch):
    monkeypatch.setattr(signatures, "required_signers", lambda c: FROZEN)
    report = signers.state(_case(verification_sent_at=None, required_signers=None,
                                 verification_revision=0))
    assert (report["frozen"], report["revision"], report["required"],
            report["signed"], report["converged"]) == (False, 0, 2, 0, False)
    assert [s["status"] for s in report["signers"]] == ["not_sent", "not_sent"]
    assert all(s["email"] is None and s["sent_at"] is None for s in report["signers"])


def test_a_link_that_is_live_reads_sent(db):
    _row(db, "P1")
    one = _by_person(signers.state(_case()))["P1"]
    assert one["status"] == "sent"
    assert one["email"] == "p1@client.com"
    assert one["sent_at"] == "2026-10-29T08:00:00+00:00"
    assert one["expires_at"] == FUTURE.isoformat()
    assert one["signed_at"] is None and one["delivery"] is None
    assert _by_person(signers.state(_case()))["P2"]["status"] == "not_sent"


def test_a_signed_director_reads_signed_with_the_time(db):
    _signed(db, "P1", "2026-10-29T08:31:00+00:00")
    one = _by_person(signers.state(_case()))["P1"]
    assert one["status"] == "signed"
    assert one["signed_at"] == "2026-10-29T08:31:00+00:00"


def test_a_link_past_its_deadline_reads_expired(db):
    _row(db, "P1", expires=(NOW - timedelta(days=1)).isoformat())
    assert _by_person(signers.state(_case()))["P1"]["status"] == "expired"


def test_a_superseded_unsigned_link_reads_expired(db):
    _row(db, "P1", outcome="superseded")
    assert _by_person(signers.state(_case()))["P1"]["status"] == "expired"


def test_a_resend_makes_the_newer_link_the_one_that_speaks(db):
    _row(db, "P1", outcome="superseded", email="old@client.com",
         sent="2026-10-29T07:00:00+00:00")
    _row(db, "P1", email="new@client.com", sent="2026-10-29T08:00:00+00:00")
    one = _by_person(signers.state(_case()))["P1"]
    assert (one["status"], one["email"]) == ("sent", "new@client.com")


def test_only_the_current_revision_counts(db):
    _signed(db, "P1", "2026-10-28T08:31:00+00:00", revision=1)
    _row(db, "P2", revision=2)
    report = signers.state(_case(verification_revision=2))
    assert _by_person(report)["P1"]["status"] == "not_sent"
    assert _by_person(report)["P2"]["status"] == "sent"
    assert report["signed"] == 0


def test_signature_captured_comes_from_the_signature_table(db):
    _signed(db, "P1", "2026-10-29T08:31:00+00:00")
    _signed(db, "P2", "2026-10-29T08:40:00+00:00")
    _sig(db, "P1")                      # P2's picture failed to store
    _sig(db, "P2", revision=0)          # and a stale one must not count
    got = _by_person(signers.state(_case()))
    assert got["P1"]["signature_captured"] is True
    assert got["P2"]["signature_captured"] is False


def test_the_suggested_email_comes_from_the_persons_record(db):
    got = _by_person(signers.state(_case()))
    assert got["P1"]["suggested_email"] == "jkoh@client.com"
    assert got["P2"]["suggested_email"] is None


def test_role_label_follows_the_consent_role(db):
    got = _by_person(signers.state(_case()))
    assert got["P1"]["role_label"] == "director"
    assert got["P2"]["role_label"] == "incoming director"


def test_set_changed_when_the_live_board_differs_from_the_frozen_one(db, monkeypatch):
    monkeypatch.setattr(signatures, "required_signers_strict", lambda c: [KOH])
    report = signers.state(_case())
    assert (report["frozen"], report["set_changed"], report["required"]) == (True, True, 2)


def test_set_changed_is_false_when_the_boards_agree(db, monkeypatch):
    monkeypatch.setattr(signatures, "required_signers_strict",
                        lambda c: list(reversed(FROZEN)))
    assert signers.state(_case())["set_changed"] is False


def test_a_read_fault_is_not_reported_as_a_changed_board(db, monkeypatch, capsys):
    """Review S4: `required_signers` answers [] to a fault, which compared with
    the frozen set read as "the board has changed" and told the operator to
    Restart verification -- discarding every collected signature."""
    def boom(case):
        raise RuntimeError("database is down")
    monkeypatch.setattr(signatures, "required_signers_strict", boom)
    report = signers.state(_case())
    assert report["set_changed"] is False
    assert report["required"] == 2
    assert "could not compare the live board" in capsys.readouterr().err


def test_a_fault_inside_the_real_live_read_is_not_a_changed_board(db, monkeypatch):
    """Same thing end to end, through the real rule rather than a stub."""
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(signatures, "get_supabase", boom)
    monkeypatch.setattr(cases, "get_supabase", boom)
    assert signers.state(_case())["set_changed"] is False


def test_converged_needs_every_signature_and_the_case_approved(db):
    _signed(db, "P1", "2026-10-29T08:31:00+00:00")
    _signed(db, "P2", "2026-10-29T08:40:00+00:00")
    assert signers.state(_case())["converged"] is False            # case not yet approved
    assert signers.state(_case(client_approved=True))["converged"] is True


def test_one_of_two_is_not_converged_even_if_the_case_says_approved(db):
    _signed(db, "P1", "2026-10-29T08:31:00+00:00")
    report = signers.state(_case(client_approved=True))
    assert (report["signed"], report["required"], report["converged"]) == (1, 2, False)


def test_the_report_carries_the_documented_keys(db):
    report = signers.state(_case())
    assert set(report) == {"multi_signer", "revision", "frozen", "set_changed",
                           "required", "signed", "converged", "signers"}
    assert set(report["signers"][0]) == {
        "person_id", "name", "roles", "role_label", "suggested_email", "status",
        "email", "sent_at", "expires_at", "signed_at", "signature_captured",
        "delivery"}


# -- latest_sends: a MagicMock chain, because the fake has no JSON-path filters -----

def _chain(rows):
    q = MagicMock()
    for name in ("table", "select", "eq", "is_", "order", "limit"):
        getattr(q, name).return_value = q
    q.execute.return_value.data = rows
    return q


def _audit(person, message_id, *, revision=1, created="2026-10-29T08:00:00+00:00",
           deliveries=True):
    meta = {"signer_person_id": person, "multi_signer": True, "revision": revision}
    if deliveries:
        meta["deliveries"] = [{"email": f"{person}@x", "message_id": message_id,
                               "person_id": person}]
    return {"created_at": created, "metadata": meta}


def test_latest_sends_asks_for_this_cases_untagged_multi_signer_sends(monkeypatch):
    q = _chain([])
    monkeypatch.setattr(signers, "get_supabase", lambda: q)
    signers.latest_sends(_case())
    eq_calls = [c.args for c in q.eq.call_args_list]
    assert ("entity_id", "C1") in eq_calls
    assert ("entity_type", "nar1_case") in eq_calls
    assert ("action_type", "EMAIL_SENT") in eq_calls
    assert ("metadata->>multi_signer", "true") in eq_calls
    q.is_.assert_called_once_with("metadata->>template", "null")
    q.order.assert_called_once_with("created_at", desc=True)
    q.limit.assert_called_once_with(100)


def test_latest_sends_keeps_the_newest_delivery_per_person(monkeypatch):
    rows = [_audit("P1", "new-1", created="2026-10-29T09:00:00+00:00"),
            _audit("P2", "only-2"),
            _audit("P1", "old-1", created="2026-10-29T07:00:00+00:00")]
    monkeypatch.setattr(signers, "get_supabase", lambda: _chain(rows))
    got = signers.latest_sends(_case())
    assert set(got) == {"P1", "P2"}
    assert got["P1"]["message_id"] == "new-1"


def test_latest_sends_skips_an_earlier_revision_and_a_row_without_deliveries(monkeypatch):
    rows = [_audit("P1", "stale", revision=1),
            _audit("P2", "none", revision=2, deliveries=False),
            _audit("P2", "good", revision=2, created="2026-10-29T06:00:00+00:00")]
    monkeypatch.setattr(signers, "get_supabase", lambda: _chain(rows))
    got = signers.latest_sends(_case(verification_revision=2))
    assert set(got) == {"P2"} and got["P2"]["message_id"] == "good"


def test_latest_sends_skips_a_row_with_an_unreadable_revision(monkeypatch):
    """Review N2: one bad row must not blank every signer's verdict."""
    rows = [_audit("P1", "bad", revision="not-a-number"), _audit("P2", "good")]
    monkeypatch.setattr(signers, "get_supabase", lambda: _chain(rows))
    assert set(signers.latest_sends(_case())) == {"P2"}


def test_latest_sends_never_raises(monkeypatch, capsys):
    q = _chain([])
    q.execute.side_effect = RuntimeError("down")
    monkeypatch.setattr(signers, "get_supabase", lambda: q)
    assert signers.latest_sends(_case()) == {}
    assert "latest_sends failed" in capsys.readouterr().err


# -- record_signing: convergence ----------------------------------------------------

def _claimed(db, person, responded):
    return _signed(db, person, responded)


def _case_row(db):
    return db.tables["nar1_cases"][0]


def test_one_of_two_signing_does_not_converge_or_touch_the_case(db):
    claimed = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(), claimed)
    assert (result["signed"], result["required"], result["converged"],
            result["won"]) == (1, 2, False, False)
    assert _case_row(db)["client_approved"] is None
    assert not [c for c in db.calls if c[0] == "nar1_cases" and c[1] == "update"]


def test_a_live_link_of_the_other_director_survives_the_first_signature(db):
    _row(db, "P2")
    claimed = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    signers.record_signing(_case(), claimed)
    other = [r for r in db.tables["nar1_client_approvals"] if r["person_id"] == "P2"][0]
    assert other["outcome"] is None


def test_the_last_signature_converges_the_case_and_wins(db):
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    result = signers.record_signing(_case(), claimed)
    assert (result["signed"], result["required"], result["converged"],
            result["won"]) == (2, 2, True, True)
    row = _case_row(db)
    assert row["client_approved"] is True
    assert row["client_response_at"] == "2026-10-29T08:40:00+00:00"
    assert row["client_approval_source"] == "self_service"
    assert row["client_approval_person_id"] is None
    # Names in the FROZEN order, not the order they signed in.
    assert row["client_approval_name"] == "Jacqueline Koh, Testing Brian"
    assert [a["person_id"] for a in result["approvals"]] == ["P1", "P2"]


def test_the_stored_provenance_reads_back_with_both_names(db):
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    signers.record_signing(_case(), _claimed(db, "P2", "2026-10-29T08:40:00+00:00"))
    summary = nar1_approvals.provenance(_case_row(db))["summary"]
    assert summary == ("Approved by Jacqueline Koh, Testing Brian using the link "
                       "in the verification email")


def test_two_concurrent_last_signers_produce_exactly_one_winner(db):
    """Both claims have landed (Postgres settles each director's own row); both
    handlers then count. The conditional UPDATE is what decides who converged."""
    first = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    second = _claimed(db, "P2", "2026-10-29T08:31:00+00:00")
    a = signers.record_signing(_case(), first)
    b = signers.record_signing(_case(), second)
    assert [a["won"], b["won"]] == [True, False]
    assert a["converged"] is True and b["converged"] is True
    assert _case_row(db)["client_approved"] is True


def test_an_nd2b_waiver_is_replaced_by_the_real_confirmation(db):
    _case_row(db).update({"client_approved": True,
                          "client_approval_source": "staff_waiver",
                          "client_approval_name": "client unreachable"})
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(client_approved=True),
                                    _claimed(db, "P2", "2026-10-29T08:40:00+00:00"))
    assert result["won"] is True
    assert _case_row(db)["client_approval_source"] == "self_service"
    assert _case_row(db)["client_approval_name"] == "Jacqueline Koh, Testing Brian"


def test_a_declined_case_never_converges(db):
    _case_row(db)["client_approved"] = False
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(client_approved=False),
                                    _claimed(db, "P2", "2026-10-29T08:40:00+00:00"))
    assert (result["converged"], result["won"]) == (True, False)
    assert _case_row(db)["client_approved"] is False


def test_a_closed_case_is_not_approved_by_a_press_that_raced_the_closure(db):
    _case_row(db)["closed_at"] = "2026-10-29T08:35:00+00:00"
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(), _claimed(db, "P2", "2026-10-29T08:40:00+00:00"))
    assert result["won"] is False
    assert _case_row(db)["client_approved"] is None


def test_an_approval_of_an_earlier_revision_does_not_count(db):
    _signed(db, "P1", "2026-10-28T08:31:00+00:00", revision=1)
    claimed = _claimed_at(db, "P2", revision=2)
    result = signers.record_signing(_case(verification_revision=2), claimed)
    assert (result["signed"], result["converged"]) == (1, False)


def _claimed_at(db, person, revision):
    return _signed(db, person, "2026-10-29T08:40:00+00:00", revision=revision)


def test_an_approval_by_someone_outside_the_frozen_set_does_not_count(db):
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P9", "2026-10-29T08:40:00+00:00")
    result = signers.record_signing(_case(), claimed)
    assert (result["signed"], result["converged"], result["won"]) == (1, False, False)


def test_an_empty_frozen_set_never_converges(db):
    claimed = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(required_signers=[]), claimed)
    assert (result["required"], result["converged"], result["won"]) == (0, False, False)
    assert _case_row(db)["client_approved"] is None


def test_a_fault_in_the_update_reports_not_won_and_does_not_raise(db, capsys, monkeypatch):
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    real = db.table

    def table(name):
        if name == "nar1_cases":
            raise RuntimeError("database is down")
        return real(name)
    monkeypatch.setattr(db, "table", table)
    result = signers.record_signing(_case(), claimed)
    assert (result["converged"], result["won"]) == (True, False)
    assert "convergence update failed" in capsys.readouterr().err


def test_a_fault_reading_the_round_reports_nothing_converged(db, capsys, monkeypatch):
    claimed = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    monkeypatch.setattr(signers, "round_approvals",
                        lambda c: (_ for _ in ()).throw(RuntimeError("down")))
    result = signers.record_signing(_case(), claimed)
    assert (result["converged"], result["won"]) == (False, False)
    assert "could not count the signatures" in capsys.readouterr().err


def test_the_clock_is_the_last_signers_not_the_converging_requests(db):
    """Review S3: P2 signed at 08:40, but P1's request (signed 08:31) is the one
    that counted both and converged."""
    first = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    result = signers.record_signing(_case(), first)
    assert result["won"] is True
    assert _case_row(db)["client_response_at"] == "2026-10-29T08:40:00+00:00"


def test_an_open_round_with_no_frozen_set_never_converges(db, monkeypatch, capsys):
    """Review S2: counting against the live rule would converge a case on fewer
    signatures than were asked for if the board has shrunk since."""
    monkeypatch.setattr(signatures, "required_signers", lambda c: [KOH])
    claimed = _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    result = signers.record_signing(_case(required_signers=None), claimed)
    assert (result["converged"], result["won"], result["required"]) == (False, False, 0)
    assert _case_row(db)["client_approved"] is None
    assert "no frozen signer set" in capsys.readouterr().err


def test_a_restart_between_the_count_and_the_write_cannot_be_overwritten(db):
    """Review S1: Restart verification clears `verification_sent_at` and leaves
    the revision alone. A handler that read the case before the restart still
    counts both signatures and still matches `client_approved IS NULL`; unbound,
    it would leave an approval on a change list reopened for editing."""
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    stale = _case()
    _case_row(db).update({"verification_sent_at": None, "required_signers": None})
    result = signers.record_signing(stale, claimed)
    assert result["won"] is False
    row = _case_row(db)
    assert row["client_approved"] is None
    assert row["verification_sent_at"] is None


def test_a_restart_and_a_new_send_under_a_later_revision_is_not_converged_by_the_old_round(db):
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    stale = _case()
    _case_row(db).update({"verification_sent_at": "2026-10-29T10:00:00+00:00",
                          "verification_revision": 2})
    assert signers.record_signing(stale, claimed)["won"] is False
    assert _case_row(db)["client_approved"] is None


def test_the_waiver_retry_is_bound_to_the_round_too(db):
    _case_row(db).update({"client_approved": True,
                          "client_approval_source": "staff_waiver"})
    _claimed(db, "P1", "2026-10-29T08:31:00+00:00")
    claimed = _claimed(db, "P2", "2026-10-29T08:40:00+00:00")
    stale = _case(client_approved=True)
    _case_row(db).update({"verification_sent_at": None})
    assert signers.record_signing(stale, claimed)["won"] is False
    assert _case_row(db)["client_approval_source"] == "staff_waiver"


# -- nar1_approvals: per-person supersede and issue ---------------------------------

def test_supersede_for_person_touches_only_that_persons_outstanding_links(db):
    mine = _row(db, "P1")
    other = _row(db, "P2")
    answered = _signed(db, "P1", "2026-10-29T08:00:00+00:00")
    elsewhere = {**_row(db, "P1"), "id": "A-other-case", "nar1_case_id": "C2"}
    db.tables["nar1_client_approvals"][-1] = elsewhere
    assert nar1_approvals.supersede_for_person("C1", "P1") == 1
    rows = {r["id"]: r for r in db.tables["nar1_client_approvals"]}
    assert rows[mine["id"]]["outcome"] == "superseded"
    assert rows[mine["id"]]["responded_at"]
    assert rows[other["id"]]["outcome"] is None
    assert rows[answered["id"]]["outcome"] == "approved"
    assert rows["A-other-case"]["outcome"] is None


def test_supersede_for_nobody_supersedes_nothing(db):
    _row(db, "P1")
    assert nar1_approvals.supersede_for_person("C1", None) == 0
    assert db.tables["nar1_client_approvals"][0]["outcome"] is None


def test_issue_for_signer_retires_only_that_signers_link_and_inserts_one(db):
    old = _row(db, "P1")
    other = _row(db, "P2")
    issued = nar1_approvals.issue_for_signer(
        case_id="C1", recipient={"email": "new@client.com", "person_id": "P1",
                                 "name": "Jacqueline Koh"},
        revision=3, expires_at=FUTURE, sent_at=NOW)
    rows = db.tables["nar1_client_approvals"]
    assert len(rows) == 3
    assert rows[0]["id"] == old["id"] and rows[0]["outcome"] == "superseded"
    assert rows[1]["id"] == other["id"] and rows[1]["outcome"] is None
    new = rows[2]
    assert (new["person_id"], new["recipient_email"], new["revision"]) == (
        "P1", "new@client.com", 3)
    assert new["token_hash"] == nar1_approvals.hash_token(issued["token"])
    assert new["expires_at"] == FUTURE.isoformat() and new["sent_at"] == NOW.isoformat()
    assert issued["token"] not in str(new)
    assert issued["revision"] == 3 and issued["expires_at"] == FUTURE
    assert issued["email"] == "new@client.com"


def test_issue_for_signer_never_supersedes_the_whole_case_or_dates_legacy_links(db, monkeypatch):
    monkeypatch.setattr(nar1_approvals, "supersede_outstanding",
                        lambda *a, **k: pytest.fail("issue_for_signer must not clear the case"))
    monkeypatch.setattr(nar1_approvals, "_date_legacy_links",
                        lambda *a, **k: pytest.fail("issue_for_signer must not date legacy links"))
    nar1_approvals.issue_for_signer(case_id="C1", recipient={"email": "a@b.com",
                                                             "person_id": "P1"},
                                    revision=2, expires_at=FUTURE)


def test_issue_for_signer_defaults_the_sent_time_to_now(db):
    nar1_approvals.issue_for_signer(case_id="C1", recipient={"email": "a@b.com",
                                                             "person_id": "P1"},
                                    revision=1, expires_at=FUTURE)
    assert db.tables["nar1_client_approvals"][0]["sent_at"]


def test_issue_still_supersedes_every_outstanding_link_on_the_case(db):
    """The NAR1 pin: the single-recipient `issue` is unchanged -- a send kills
    every earlier link, whoever held it."""
    a = _row(db, "P1")
    b = _row(db, "P2")
    nar1_approvals.issue(case_id="C1", recipients=[{"email": "x@y.com", "person_id": "P1"}],
                         revision=2)
    rows = {r["id"]: r for r in db.tables["nar1_client_approvals"]}
    assert rows[a["id"]]["outcome"] == "superseded"
    assert rows[b["id"]]["outcome"] == "superseded"


# -- the auto-approval job cannot reach an ND2 case ---------------------------------

def test_auto_approval_refuses_a_multi_signer_officer_change():
    case = {"id": "C1", "form_code": "Nd2a", "multi_signer": True,
            "client_approved": None, "verification_sent_at": NOW.isoformat(),
            "closed_at": None}
    assert job.skip_reason(case) == "an officer change is never approved on silence"
    assert job.skip_reason({**case, "form_code": "Nd2b"}) == (
        "an officer change is never approved on silence")


def test_the_job_selects_annual_returns_only_in_its_query(monkeypatch):
    q = MagicMock()
    for name in ("table", "select", "eq", "is_", "lt", "order", "limit"):
        getattr(q, name).return_value = q
    q.execute.return_value.data = []
    monkeypatch.setattr(job, "get_supabase", lambda: q)
    job.due_tokens(NOW)
    assert ("nar1_cases.form_code", "Nar1") in [c.args for c in q.eq.call_args_list]
