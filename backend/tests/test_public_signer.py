"""The public Confirm & File page when several directors must sign
(nd2-multi-signer, spec 2.5, 2.6, 6 item 3 and test groups 9 and 10).

The collaborators that matter here are REAL on purpose: `signers`,
`nar1_approvals` and `nar1_cases.get_case` run against the in-memory
`FakeSupabase`, because the thing under test is how a director's press turns
into a claimed row, a count and one conditional UPDATE, and a mock of any of
those would assert the mock. What is patched is everything that leaves the
process: the audit writer, the receipt mailer, the signature store and the
entity lookup. No test reaches Supabase, Resend or DNS.

`tests/test_public_approval.py` is deliberately not edited: it is the proof that
single-mode ND2 and NAR1 are unchanged.
"""
import base64
import io
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from main import app
from routers import public_approval
from services import approval_receipt, nar1_approvals, nar1_cases
from services import audit_events as ev
from services.officer_changes import cases, signatures, signers
from tests.officer_changes.fakes import FakeSupabase

T1 = "abcdefghijklmnopqrstuvwxyz000001"      # Jacqueline Koh's link
T2 = "abcdefghijklmnopqrstuvwxyz000002"      # Testing Brian's link
T3 = "abcdefghijklmnopqrstuvwxyz000003"      # someone outside the set
PATH = "/public/officer-change-approval/{}"

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
FUTURE = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

KOH = {"person_id": "P1", "name": "Jacqueline Koh", "roles": ["resolution"]}
BRIAN = {"person_id": "P2", "name": "Testing Brian", "roles": ["consent", "resolution"]}
ENTITY = {"id": "E1", "company_name": "ACME LIMITED", "br_number": "00000001"}


def _drawing() -> str:
    img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(20, 150), (120, 40), (200, 160), (320, 60)],
                             fill=(26, 32, 80, 255), width=6)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _scripts(text: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>.*?</script>", text, flags=re.S | re.I)


def _case(**over):
    return {"id": "C1", "entity_id": "E1", "case_no": "ND2A-2026-0001",
            "form_code": "Nd2a", "multi_signer": True, "client_approved": None,
            "client_approval_source": None, "closed_at": None,
            "verification_sent_at": NOW.isoformat(), "verification_revision": 1,
            "required_signers": [KOH, BRIAN], **over}


def _link(rid, token, person, name, **over):
    return {"id": rid, "nar1_case_id": "C1", "person_id": person,
            "recipient_email": f"{person.lower()}@client.com", "recipient_name": name,
            "token_hash": nar1_approvals.hash_token(token), "outcome": None,
            "revision": 1, "sent_at": "2026-10-29T08:00:00+00:00",
            "expires_at": FUTURE, "responded_at": None, **over}


class World:
    """Everything one test needs a handle on."""

    def __init__(self, db, log, receipts, claim, supersede, store):
        self.db, self.log, self.receipts = db, log, receipts
        self.claim, self.supersede, self.store = claim, supersede, store

    @property
    def case(self):
        return self.db.tables["nar1_cases"][0]

    def link(self, rid):
        return next(r for r in self.db.tables["nar1_client_approvals"] if r["id"] == rid)

    def logged(self, code):
        return [c for c in self.log.await_args_list if c.kwargs["action_type"] == code]

    def writes(self):
        return [c for c in self.db.calls if c[1] != "select"]


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    public_approval._HITS.clear()
    yield
    public_approval._HITS.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def world(monkeypatch, _no_receipt_mail_in_tests):
    db = FakeSupabase({
        "nar1_cases": [_case()],
        "nar1_client_approvals": [_link("A1", T1, "P1", "Jacqueline Koh"),
                                  _link("A2", T2, "P2", "Testing Brian")],
        "officer_change_signatures": [],
        "persons": [], "contacts": [],
    })
    for module in (signers, signatures, cases, nar1_approvals, nar1_cases):
        monkeypatch.setattr(module, "get_supabase", lambda: db)
    with patch("routers.public_approval.nar1_cases.entity_for", return_value=ENTITY), \
         patch("routers.public_approval.log_event", new=AsyncMock()) as log, \
         patch("routers.public_approval.nar1_approvals.claim",
               wraps=nar1_approvals.claim) as claim, \
         patch("routers.public_approval.nar1_approvals.supersede_outstanding",
               wraps=nar1_approvals.supersede_outstanding) as supersede, \
         patch("routers.public_approval.signatures.store",
               return_value={"id": "sig-1"}) as store:
        yield World(db, log, _no_receipt_mail_in_tests, claim, supersede, store)


def sign(client, token, *, drawing=True):
    data = {"signature": _drawing()} if drawing else {}
    return client.post(PATH.format(token), data=data)


# --------------------------------------------------------------------------- #
#  The ask page
# --------------------------------------------------------------------------- #

def test_the_ask_page_has_the_pad_and_says_each_director_signs(client, world):
    text = client.get(PATH.format(T1)).text
    assert '<canvas id="sigpad"' in text
    assert "Each director signs from their own email." in text
    assert "The form is filed once every director has signed." in text
    assert text.index("Your signature") < text.index("Warning") < text.index("sigok")


def test_the_ask_page_runs_the_pad_and_nothing_else(client, world):
    scripts = _scripts(client.get(PATH.format(T1)).text)
    assert len(scripts) == 1 and "src=" not in scripts[0].lower()
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon"):
        assert forbidden not in scripts[0]


def test_a_GET_writes_nothing_at_all(client, world):
    client.get(PATH.format(T1))
    assert world.writes() == []
    world.log.assert_not_awaited()
    world.claim.assert_not_called()
    world.store.assert_not_called()
    world.receipts.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  A director who signs before the others
# --------------------------------------------------------------------------- #

def test_the_first_signer_is_told_it_is_recorded_and_the_others_are_awaited(client, world):
    text = sign(client, T1).text
    assert "Thank you — your signature is recorded" in text
    assert "will be filed once the other directors have signed" in text
    assert "1 of 2 directors have signed" in text
    assert "You will receive the signed form by email once everyone has signed." in text
    assert "ACME LIMITED" in text


def test_the_waiting_page_names_nobody_else_and_runs_no_script(client, world):
    text = sign(client, T1).text
    assert "Testing Brian" not in text and "p2@client.com" not in text
    assert _scripts(text) == []


def test_the_first_signer_claims_and_keeps_a_signature_but_does_not_converge(client, world):
    sign(client, T1)
    assert world.link("A1")["outcome"] == "approved"
    world.store.assert_called_once()
    assert world.case["client_approved"] is None
    # The other director's link is untouched, and nothing was mailed or superseded.
    assert world.link("A2")["outcome"] is None
    world.supersede.assert_not_called()
    world.receipts.assert_not_awaited()
    assert world.logged(ev.CASE_STATUS_CHANGED) == []


def test_the_signing_is_audited_with_the_count_and_never_the_image(client, world):
    sign(client, T1)
    (call,) = world.logged(ev.CLIENT_APPROVAL_SELF_SERVICE)
    meta = call.kwargs["metadata"]
    assert meta["multi_signer"] == {"signed": 1, "required": 2, "converged": False}
    assert meta["person_id"] == "P1" and meta["channel"] == "self_service"
    assert meta["signature"] == {"captured": True, "signature_id": "sig-1"}
    assert "data:image" not in repr(call.kwargs)
    assert call.kwargs["user_id"] is None


def test_a_GET_after_signing_shows_the_waiting_page_with_the_count(client, world):
    sign(client, T1)
    world.log.reset_mock()
    text = client.get(PATH.format(T1)).text
    assert "your signature is recorded" in text and "1 of 2" in text
    assert world.logged(ev.CLIENT_APPROVAL_SELF_SERVICE) == []


# --------------------------------------------------------------------------- #
#  The last signer converges the case
# --------------------------------------------------------------------------- #

def test_the_last_signer_converges_the_case_and_sees_the_all_signed_page(client, world):
    sign(client, T1)
    text = sign(client, T2).text
    assert "Thank you — every director has now signed" in text
    assert "We will file Form ND2A for ACME LIMITED." in text
    assert "The signed form is on its way to you by email." in text
    assert _scripts(text) == []
    case = world.case
    assert case["client_approved"] is True
    assert case["client_approval_source"] == "self_service"
    assert case["client_approval_name"] == "Jacqueline Koh, Testing Brian"
    assert case["client_approval_person_id"] is None


def test_convergence_writes_one_status_row_in_the_automatic_actors_name(client, world):
    sign(client, T1)
    sign(client, T2)
    (call,) = world.logged(ev.CASE_STATUS_CHANGED)
    assert call.kwargs["user_id"] is None
    assert call.kwargs["user_display_name"] == approval_receipt.ACTOR
    assert call.kwargs["old_value"] == "awaiting_client"
    assert call.kwargs["new_value"] == "approved"
    meta = call.kwargs["metadata"]
    assert meta["reason"] == "every required director has signed"
    assert meta["revision"] == 1
    assert [s["person_id"] for s in meta["signers"]] == ["P1", "P2"]
    last = world.logged(ev.CLIENT_APPROVAL_SELF_SERVICE)[-1].kwargs["metadata"]
    assert last["multi_signer"] == {"signed": 2, "required": 2, "converged": True}


def test_convergence_supersedes_leftover_links_and_queues_a_receipt_per_signer(client, world):
    sign(client, T1)
    sign(client, T2)
    world.supersede.assert_called_once_with("C1")
    queued = {c.args[1]["person_id"]: c.args for c in world.receipts.await_args_list}
    assert set(queued) == {"P1", "P2"}
    assert all(args[0] == "C1" for args in queued.values())
    assert queued["P1"][1]["recipient_email"] == "p1@client.com"
    assert queued["P2"][1]["outcome"] == "approved"


def test_an_early_signer_gets_no_receipt_until_everyone_has_signed(client, world):
    sign(client, T1)
    assert world.receipts.await_count == 0
    sign(client, T2)
    assert world.receipts.await_count == 2


def test_after_convergence_every_link_says_everyone_has_signed(client, world):
    sign(client, T1)
    sign(client, T2)
    for token in (T1, T2):
        assert "every director has now signed" in client.get(PATH.format(token)).text


def test_a_replayed_POST_is_idempotent(client, world):
    sign(client, T1)
    world.claim.reset_mock()
    world.store.reset_mock()
    world.log.reset_mock()
    text = sign(client, T1).text
    assert "your signature is recorded" in text and "1 of 2" in text
    world.claim.assert_not_called()
    world.store.assert_not_called()
    assert world.logged(ev.CLIENT_APPROVAL_SELF_SERVICE) == []


def test_a_replay_after_convergence_does_not_converge_again(client, world):
    sign(client, T1)
    sign(client, T2)
    world.log.reset_mock()
    world.receipts.reset_mock()
    text = sign(client, T2).text
    assert "every director has now signed" in text
    assert world.logged(ev.CASE_STATUS_CHANGED) == []
    world.receipts.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  Concurrency and S6
# --------------------------------------------------------------------------- #

def test_two_last_signers_pressing_together_converge_the_case_once(client, world):
    """Both handlers read the round after BOTH claims have landed, which is what
    two directors pressing in the same second produces. Both see two of two;
    only the UPDATE that matched `client_approved IS NULL` may act."""
    real = signers.round_approvals

    def both_landed(case):
        rows = real(case)
        return [{**r, "outcome": "approved",
                 "responded_at": r.get("responded_at") or "2026-10-29T09:00:00+00:00"}
                for r in rows]

    with patch("services.officer_changes.signers.round_approvals", side_effect=both_landed):
        first = sign(client, T1).text
        second = sign(client, T2).text
    assert "every director has now signed" in first
    assert "every director has now signed" in second
    assert len(world.logged(ev.CASE_STATUS_CHANGED)) == 1
    assert world.receipts.await_count == 2
    world.supersede.assert_called_once_with("C1")


def _fail_the_first_case_update(world):
    """Make the convergence UPDATE of `nar1_cases` raise until told otherwise."""
    state = {"fail": True}
    real_table = world.db.table

    def table(name):
        query = real_table(name)
        if name == "nar1_cases":
            execute = query.execute

            def guarded():
                if state["fail"] and query._op == "update":
                    raise RuntimeError("the database went away")
                return execute()
            query.execute = guarded
        return query

    world.db.table = table
    return state


def test_S6_a_replay_from_a_signed_director_retries_a_convergence_that_failed(client, world):
    state = _fail_the_first_case_update(world)
    sign(client, T1)
    sign(client, T2)                       # everyone has signed; the UPDATE failed
    assert world.case["client_approved"] is None
    assert world.logged(ev.CASE_STATUS_CHANGED) == []
    world.receipts.assert_not_awaited()

    state["fail"] = False                  # the database is back
    world.claim.reset_mock()
    text = sign(client, T2).text           # the director presses again
    assert "every director has now signed" in text
    world.claim.assert_not_called()        # a replay never claims twice
    assert world.case["client_approved"] is True
    assert len(world.logged(ev.CASE_STATUS_CHANGED)) == 1
    assert world.receipts.await_count == 2
    # The signing itself was audited once, on the original press.
    assert len(world.logged(ev.CLIENT_APPROVAL_SELF_SERVICE)) == 2


def test_S6_the_first_signers_replay_can_also_finish_the_job(client, world):
    state = _fail_the_first_case_update(world)
    sign(client, T1)
    sign(client, T2)
    state["fail"] = False
    sign(client, T1)
    assert world.case["client_approved"] is True
    assert len(world.logged(ev.CASE_STATUS_CHANGED)) == 1


def test_S1_a_convergence_that_failed_does_not_promise_a_mail_that_is_not_coming(client, world):
    _fail_the_first_case_update(world)
    sign(client, T1)
    text = sign(client, T2).text
    assert world.case["client_approved"] is None
    assert "on its way" not in text and "every director has now signed" not in text
    assert "your signature is recorded" in text
    assert "renewal@getstarted.hk" in text
    assert _scripts(text) == []
    assert "Jacqueline Koh" not in text


def test_S1_the_same_page_is_not_shown_when_another_request_already_converged(client, world):
    """Not won, but the case IS approved: that is a plain all-signed answer."""
    sign(client, T1)
    real = signers.record_signing

    def lost(case, claimed):
        return {**real(case, claimed), "won": False}

    with patch("routers.public_approval.signers.record_signing", side_effect=lost):
        text = sign(client, T2).text
    # record_signing really converged the case; only the `won` flag was withheld.
    assert world.case["client_approved"] is True
    assert "every director has now signed" in text


def test_a_GET_never_retries_the_convergence(client, world):
    state = _fail_the_first_case_update(world)
    sign(client, T1)
    sign(client, T2)
    state["fail"] = False
    client.get(PATH.format(T2))
    assert world.case["client_approved"] is None


# --------------------------------------------------------------------------- #
#  The signature is always required
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("data", [{}, {"signature": ""}, {"signature": "<b>x</b>"}])
def test_a_missing_or_unreadable_signature_claims_nothing(client, world, data):
    response = client.post(PATH.format(T1), data=data)
    assert "We could not read your signature" in response.text
    assert "<b>x</b>" not in response.text
    assert '<canvas id="sigpad"' in response.text
    world.claim.assert_not_called()
    world.store.assert_not_called()
    world.log.assert_not_awaited()
    assert world.link("A1")["outcome"] is None


# --------------------------------------------------------------------------- #
#  Who may use a link
# --------------------------------------------------------------------------- #

def _unavailable(text):
    return "This link is no longer available" in text


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_link_for_someone_outside_the_frozen_set_is_unavailable(client, world, method):
    world.db.tables["nar1_client_approvals"].append(
        _link("A9", T3, "P9", "Stranger Danger"))
    response = (client.get(PATH.format(T3)) if method == "get"
                else sign(client, T3))
    assert _unavailable(response.text)
    world.claim.assert_not_called()
    assert world.link("A9")["outcome"] is None


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_stale_revision_link_gets_todays_answer(client, world, method):
    world.case["verification_revision"] = 2
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    world.claim.assert_not_called()


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_declined_case_is_unavailable_to_every_signer(client, world, method):
    world.case["client_approved"] = False
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    world.claim.assert_not_called()


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_closed_case_is_unavailable_and_says_nothing_about_why(client, world, method):
    world.case["closed_at"] = "2026-10-30T00:00:00+00:00"
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    assert "closed" not in response.text.lower().replace("nothing has been changed", "")
    world.claim.assert_not_called()


@pytest.mark.parametrize("method", ["get", "post"])
def test_B1_a_stale_link_on_a_converged_case_names_nobody_and_claims_no_rule(
        client, world, method):
    """Both sign, then the operator restarts into revision 2 and a director opens
    the revision-1 email. The single-mode answer would name one director and say
    that only one confirmation is required, which is false in this mode."""
    sign(client, T1)
    sign(client, T2)
    world.case["verification_revision"] = 2
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    text = response.text
    assert "Jacqueline Koh" not in text and "Testing Brian" not in text
    assert "Only one confirmation" not in text and "already been confirmed" not in text
    assert "every director has now signed" in text


@pytest.mark.parametrize("method", ["get", "post"])
def test_B1_a_stale_link_on_an_open_round_is_the_unavailable_page(client, world, method):
    world.case["verification_revision"] = 2
    world.link("A1")["outcome"] = "approved"
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    assert "Jacqueline Koh" not in response.text


def test_a_signed_directors_replay_on_a_declined_case_is_unavailable_not_waiting(client, world):
    sign(client, T1)
    world.case["client_approved"] = False
    assert _unavailable(sign(client, T1).text)


@pytest.mark.parametrize("method", ["get", "post"])
def test_an_expired_unsigned_link_is_unavailable(client, world, method):
    world.link("A1")["expires_at"] = (datetime.now(timezone.utc)
                                      - timedelta(days=1)).isoformat()
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    world.claim.assert_not_called()


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_superseded_link_is_unavailable_while_the_case_is_open(client, world, method):
    world.link("A1")["outcome"] = "superseded"
    response = (client.get(PATH.format(T1)) if method == "get" else sign(client, T1))
    assert _unavailable(response.text)
    world.claim.assert_not_called()


def test_losing_the_claim_to_a_concurrent_press_reads_as_signed(client, world):
    """Two tabs of one director's link: the second claim finds the row answered."""
    with patch("routers.public_approval.nar1_approvals.claim") as claim:
        def lose(approval_id, **kw):
            world.link("A1")["outcome"] = "approved"
            world.link("A1")["responded_at"] = "2026-10-29T09:00:01+00:00"
            return None
        claim.side_effect = lose
        text = sign(client, T1).text
    assert "your signature is recorded" in text
    world.store.assert_not_called()
    world.log.assert_not_awaited()


# --------------------------------------------------------------------------- #
#  An ND2B filed without confirmation
# --------------------------------------------------------------------------- #

def test_a_waiver_does_not_hide_the_ask_page_and_convergence_replaces_it(client, world):
    world.case.update(form_code="Nd2b", client_approved=True,
                      client_approval_source="staff_waiver")
    assert '<canvas id="sigpad"' in client.get(PATH.format(T1)).text
    sign(client, T1)
    sign(client, T2)
    assert world.case["client_approved"] is True
    assert world.case["client_approval_source"] == "self_service"
    assert world.case["client_approval_name"] == "Jacqueline Koh, Testing Brian"
    assert len(world.logged(ev.CASE_STATUS_CHANGED)) == 1


# --------------------------------------------------------------------------- #
#  Single mode and NAR1 are untouched (spec 6, item 3)
# --------------------------------------------------------------------------- #

def _hits() -> int:
    return sum(len(v) for k, v in public_approval._HITS.items() if k.startswith("t:"))


def test_a_multi_signer_request_is_rate_limited_once(client, world):
    client.get(PATH.format(T1))
    assert _hits() == 1
    public_approval._HITS.clear()
    sign(client, T1)
    assert _hits() == 1


def test_a_single_mode_request_is_rate_limited_once(client, world):
    world.case["multi_signer"] = False
    with patch("routers.public_approval.signatures.must_sign", return_value=False):
        client.get(PATH.format(T1))
        assert _hits() == 1
        public_approval._HITS.clear()
        client.post(PATH.format(T1))
    assert _hits() == 1


def test_single_mode_never_reaches_the_signer_functions(client, world):
    world.case["multi_signer"] = False
    with patch("routers.public_approval._show_signer", side_effect=AssertionError), \
         patch("routers.public_approval._record_signer", side_effect=AssertionError), \
         patch("routers.public_approval.signatures.must_sign", return_value=False):
        assert client.get(PATH.format(T1)).status_code == 200
        assert "your confirmation is recorded" in client.post(PATH.format(T1)).text
    assert world.case["client_approved"] is True


def _nar1_world(world):
    world.case.update(form_code="Nar1", case_no="NAR-2026-0041", ar_period_year=2026,
                      multi_signer=True)          # a NAR1 row can never carry it; the page must not trust it
    for rid in ("A1", "A2"):
        world.link(rid).pop("revision")


NAR1 = "/public/nar1-approval/{}"


def test_the_NAR1_routes_never_reach_the_signer_functions_even_for_a_multi_signer_dict(
        client, world):
    _nar1_world(world)
    with patch("routers.public_approval._show_signer", side_effect=AssertionError), \
         patch("routers.public_approval._record_signer", side_effect=AssertionError):
        assert client.get(NAR1.format(T1)).status_code == 200
        text = client.post(NAR1.format(T1)).text
    assert "Thank you — your confirmation is recorded" in text


def test_NAR1_still_supersedes_the_other_links_with_exclude_id(client, world):
    _nar1_world(world)
    client.post(NAR1.format(T1))
    world.supersede.assert_called_once_with("C1", exclude_id="A1")
    assert world.link("A2")["outcome"] == "superseded"


def test_the_NAR1_page_has_no_script(client, world):
    _nar1_world(world)
    assert "<script" not in client.get(NAR1.format(T1)).text.lower()


def test_a_NAR1_request_is_rate_limited_once(client, world):
    _nar1_world(world)
    client.get(NAR1.format(T1))
    assert _hits() == 1


def test_an_NAR1_token_on_the_ND2_page_is_unavailable_in_either_mode(client, world):
    _nar1_world(world)
    assert _unavailable(client.get(PATH.format(T1)).text)


# --------------------------------------------------------------------------- #
#  The ask page's two new optional arguments
# --------------------------------------------------------------------------- #

KWARGS = dict(company="ACME", br_number="1", form_code="Nd2a", case_no="X",
              deadline="1 Nov 2026")


def test_the_defaults_reproduce_todays_page_byte_for_byte():
    plain = public_approval._ask_officer_change(**KWARGS, sign=True).body
    assert public_approval._ask_officer_change(**KWARGS, sign=True, note="").body == plain
    assert b'class="note">Each director' not in plain


def test_a_note_is_printed_once_and_escaped():
    body = public_approval._ask_officer_change(**KWARGS, note="<i>x</i> & y").body.decode()
    assert body.count("&lt;i&gt;x&lt;/i&gt; &amp; y") == 1
    assert "<i>x</i>" not in body


def test_sign_none_still_asks_must_sign_for_this_person():
    case = {"form_code": "Nd2a", "case_no": "X", "id": "C1"}
    with patch("routers.public_approval.signatures.must_sign", return_value=True) as ask:
        page = public_approval._officer_change_ask(
            case, ENTITY, {"person_id": "P1", "expires_at": FUTURE})
    ask.assert_called_once_with(case, "P1")
    assert b'<canvas id="sigpad"' in page.body
