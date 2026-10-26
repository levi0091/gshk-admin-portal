"""QA scenario regression: the PROD duplicate-NAR1 incident, replayed against a simulated CR.

Ticket 01 (nar1-duplicate-submission), QA round 01. Not a unit test of any one
function: it drives the real routes, `filings` service and `TpsiClient` against
`cr_harness` (an in-memory Supabase and an `httpx.MockTransport` CR) and asks
the one question that matters to GSHK: HOW MANY COPIES OF THE SAME ANNUAL
RETURN DOES CR HOLD AT THE END?  `SlowCR.lodged` is that number. It counts
every submitFormNar1 request CR RECEIVED, whether or not our client was still
listening, because CR lodges and charges on receipt.

THE SAME FILE RUNS ON MASTER (0a3f9b8) AND ON THE FIX. It uses nothing but the
HTTP routes both versions have, and is tolerant of wiring that exists only on
the fix. On master the scenarios must FAIL (CR holds 2-4 copies); on the fix
they must PASS (exactly 1, except the one explicit, operator-confirmed path).

SAFETY. Nothing here can reach a real service:
  * Supabase is `FakeStore`; `DATABASE_URL`/`SUPABASE_*` are removed;
  * CR is an in-process `httpx.MockTransport`;
  * Resend and DNS are never imported on this path;
  * an autouse fixture makes `socket.connect`/`getaddrinfo` raise, so a wiring
    mistake on the old code fails loudly instead of leaving the machine.

Run (from backend/):  python -m pytest -q tests/tpsi/test_prod_incident_scenario.py
Per-scenario CR counts are appended to $QA_SCENARIO_LOG when it is set.
"""
import os
import socket
import threading
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from services.tpsi import filings
from tests.tpsi import cr_harness
from tests.tpsi.cr_harness import (H, RECEIPT, SUPER, FakeCR, Harness, ago,
                                   doc_status_reply, seed)

SUBMIT = "/tpsi/submitFormNar1"

#: True on the fix, False on master: the fix introduced the claim stage.
FIX = hasattr(filings, "STAGE_SUBMITTING")
fix_only = pytest.mark.skipif(not FIX, reason="the fix's routes/stages only")

#: The sweep cut-off on the fix (code, migration and view agree on 370 s).
STALE = getattr(filings, "STALE_CLAIM_SECONDS", 370)

#: A claim made on 23 Oct 2026 08:30 HKT: long past any in-flight window, and
#: the date the receipts below carry.
CLAIMED = "2026-10-23T00:30:00+00:00"
RECEIPT_IN = {
    "caseNo": "180256934", "pymtNo": "5010475972", "pymtRefNo": "733037536",
    "pymtMtd": "Deduct from Account", "transactionDate": "23/10/2026",
    "transactionTime": "09:15:30", "totalAmount": "2610.00",
    "paymentRcptList": [{"rcptNo": "D7700", "revCode": "16",
                         "docShtFrm": "NAR1L", "amtChrg": "2610.00"}],
}


# --------------------------------------------------------------------------- #
#  Safety net: no test in this file may open a socket.
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("QA scenario tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY",
                 "DATABASE_URL", "RESEND_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
#  A CR that takes as long as it is told to, and lodges on receipt
# --------------------------------------------------------------------------- #

@dataclass
class SlowCR(FakeCR):
    """CR with a script, one step per submitFormNar1 request that reaches it.

    A step is a dict:
      latency   seconds CR takes to answer (default 30);
      receives  False -> the request never arrives (connect timeout);
      drop      True  -> CR lodges, then the connection dies before the reply.

    The client's own read timeout (60 s on master, 180 s for submitForm on the
    fix) is taken from the request, exactly as httpx would apply it: a latency
    above it raises `ReadTimeout` -- while CR, having received the form,
    lodges it anyway. That is the whole incident.
    """
    script: list = field(default_factory=lambda: [{"latency": 30}])
    lodged: int = 0
    hits: int = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/ICRIS3EF")
        if path != SUBMIT:
            return super().handler(request)
        step = self.script[min(self.hits, len(self.script) - 1)]
        self.hits += 1
        self.calls.append(path)
        read_timeout = request.extensions.get("timeout", {}).get("read")
        self.timeouts.setdefault(path, []).append(read_timeout)
        if path in self.on_call:
            self.on_call[path]()
        if step.get("receives", True) is False:
            raise httpx.ConnectTimeout("connect timed out")
        self.lodged += 1                      # CR has it, and has charged
        if step.get("drop"):
            raise httpx.RemoteProtocolError("Server disconnected without a reply")
        if step.get("latency", 30) > (read_timeout or 0):
            raise httpx.ReadTimeout("The read operation timed out")
        return httpx.Response(200, content=RECEIPT)


class Portal(Harness):
    """`Harness`, tolerant of wiring that only exists on one side of the fix."""

    def __init__(self, store=None, cr=None, user=None):
        super().__init__(store, cr or SlowCR(), user)

    def __enter__(self):
        from main import app

        async def record(**kwargs):
            self.events.append(kwargs)

        shared = SimpleNamespace(account_id="PRESENTER", tpsi_password="pw",
                                 deposit_account_no="ACC")
        sb = lambda: self.store  # noqa: E731
        self._stack.enter_context(patch.dict(os.environ))
        os.environ.pop("DATABASE_URL", None)
        must = [
            ("services.tpsi.filings.get_supabase", sb),
            ("routers.tpsi.get_supabase", sb),
            ("routers.tpsi.client_for", lambda *a, **k: self.tpsi),
            ("routers.tpsi.shared_credentials.load_for_use", lambda: shared),
            ("middleware.auth._resolve_user", lambda *a, **k: self.user),
        ]
        maybe = [
            ("services.nar1_cases.get_supabase", sb),
            ("routers.cases.get_supabase", sb),
            ("services.tpsi.audit_context.get_supabase", sb),
            ("services.tpsi.shared_credentials.deposit_account_no", lambda: "ACC"),
            ("services.tpsi.shared_credentials.record_password_expiry",
             lambda *_a: None),
            ("routers.tpsi.credentials.load_eservice", lambda _u: ("USERID", "pw")),
            ("services.tpsi.crypto.build_pin_sign", lambda *a, **k: "<cr:PinSign/>"),
            ("services.tpsi.crypto.signing_public_key_pem", lambda *_a: "pem"),
            ("services.tpsi.drift.current_xml_for",
             lambda filing: filing.get("request_xml") or ""),
            ("services.nar1_approvals.supersede_outstanding", lambda *a, **k: 0),
        ]
        for target, value in must:
            self._stack.enter_context(patch(target, value))
        for target, value in maybe:
            try:
                self._stack.enter_context(patch(target, value))
            except (AttributeError, ModuleNotFoundError):
                pass
        for target in ("routers.tpsi.log_event", "routers.cases.log_event",
                       "services.audit_service.log_event"):
            try:
                self._stack.enter_context(patch(target, side_effect=record))
            except (AttributeError, ModuleNotFoundError):
                pass
        self.http = TestClient(app, raise_server_exceptions=False)
        return self

    # ---- extra buttons ----------------------------------------------------
    def poll(self):
        return self.http.get("/tpsi/filings/f1", headers=H)

    def resolve(self, **body):
        return self.http.post("/tpsi/filings/f1/resolve", headers=H, json=body)

    def lodged(self) -> int:
        return self.cr.lodged

    def hammer(self, rounds: int = 3):
        """What the PROD operators did: validate, sign, submit -- again."""
        out = []
        for _ in range(rounds):
            out.append((self.validate().status_code, self.sign().status_code,
                        self.submit().status_code))
        return out


def record(name: str, lodged: int, allowed: int) -> None:
    line = f"{name}\t{lodged}\t{allowed}"
    print("SCENARIO-COUNT", line)
    path = os.environ.get("QA_SCENARIO_LOG")
    if path:
        with open(path, "a") as fh:
            fh.write(line + "\n")


def check(name: str, h: Portal, allowed: int = 1) -> None:
    record(name, h.cr.lodged, allowed)
    assert h.cr.lodged == allowed, (
        f"[{name}] CR holds {h.cr.lodged} copies of this annual return; "
        f"it must hold {allowed}")


# --------------------------------------------------------------------------- #
#  1. The incident, exactly as it happened to Fashion Hamburg, NAR-2026-0319
# --------------------------------------------------------------------------- #

def test_01_fashion_hamburg_replay_slow_slow_fast():
    """23 Oct: submit -> timeout -> re-validate/sign -> submit -> timeout ->
    re-validate/sign -> submit -> success. CR: 'Forms NAR1 for 2026 x3'."""
    with Portal(cr=SlowCR(script=[{"latency": 90}, {"latency": 90},
                                  {"latency": 45}])) as h:
        h.submit()
        h.hammer(2)                       # the two retries the operators made
        check("01 Fashion Hamburg replay (90s,90s,45s)", h)


def test_02_cr_slow_but_inside_180s_is_one_filing_and_succeeds():
    with Portal(cr=SlowCR(script=[{"latency": 150}] * 4)) as h:
        first = h.submit()
        h.hammer(2)
        record("02 CR 150s", h.cr.lodged, 1)
        assert h.cr.lodged == 1
        if FIX:
            assert first.status_code == 202
            assert h.stage() == "submitted", "150 s is inside the 180 s wait"
            assert h.cr.timeouts[SUBMIT][0] == 180
            others = {p: t for p, ts in h.cr.timeouts.items()
                      if p != SUBMIT for t in ts}
            assert set(others.values()) <= {60, 60.0}, (
                "every other CR call keeps the 60 s read timeout")


def test_03_cr_slower_than_180s_is_unknown_never_refused():
    with Portal(cr=SlowCR(script=[{"latency": 250}] * 4)) as h:
        h.submit()
        h.hammer(3)
        check("03 CR 250s (past 180s)", h)
        if FIX:
            assert h.stage() == "submission_unknown"
            assert "TPSI_SUBMISSION_UNKNOWN" in h.actions()


def test_04_cr_lodges_then_drops_the_connection():
    with Portal(cr=SlowCR(script=[{"drop": True}] * 4)) as h:
        h.submit()
        h.hammer(3)
        check("04 CR lodges then drops", h)
        if FIX:
            assert h.stage() == "submission_unknown"


# --------------------------------------------------------------------------- #
#  2. CR never receives it: the one place a second request is correct
# --------------------------------------------------------------------------- #

def test_05_cr_never_receives_it_then_operator_declares_not_lodged_once_safe():
    """CR unreachable on the first try. Nothing was lodged (0 copies), the
    portal still says 'unknown', and the retry is possible only after the
    operator has waited out the in-flight window and ticked 'I checked CR'.
    Final: exactly 1 copy -- the explicit, operator-confirmed path."""
    with Portal(cr=SlowCR(script=[{"receives": False}, {"latency": 30}])) as h:
        h.submit()
        if FIX:
            assert h.stage() == "submission_unknown"
            assert h.hammer(3) == [(409, 409, 409)] * 3
            assert h.cr.lodged == 0, "an unknown outcome may not reach CR again"
            # Too soon: the first call may still be answering.
            h.store.get("tpsi_filings", "f1")["submit_started_at"] = ago(60)
            early = h.resolve(outcome="not_lodged", checked_cr=True)
            assert early.status_code == 409, "declared before the window closed"
            # Without the tick: refused.
            h.store.get("tpsi_filings", "f1")["submit_started_at"] = ago(STALE + 30)
            assert h.resolve(outcome="not_lodged").status_code == 400
            ok = h.resolve(outcome="not_lodged", checked_cr=True)
            assert ok.status_code == 200 and h.stage() == "submission_failed"
            assert h.validate().status_code == 200
            assert h.sign().status_code == 200
            assert h.submit().status_code == 202
            assert h.stage() == "submitted"
        else:
            h.hammer(1)
        check("05 never received, declared not lodged (explicit path)", h)


def test_06_operator_wrongly_declares_not_lodged_is_the_only_road_to_a_second_copy():
    """Residual risk, stated plainly. CR DID lodge; the operator waits the full
    window, ticks 'I checked CR' (wrongly) and files again. CR then holds 2.
    Allowed by design (an explicit, human, post-window, ticked act) -- and it
    is the ONLY way to get there. Everything short of it is covered above."""
    with Portal(cr=SlowCR(script=[{"latency": 250}, {"latency": 30}])) as h:
        h.submit()
        h.hammer(2)
        record("06 before any declaration", h.cr.lodged, 1)
        assert h.cr.lodged == 1
        h.store.get("tpsi_filings", "f1")["submit_started_at"] = ago(STALE + 30)
        assert h.resolve(outcome="not_lodged", checked_cr=True).status_code == 200
        h.validate(); h.sign(); h.submit()
        check("06 wrong 'not lodged' declaration (documented residual)", h, 2)


# --------------------------------------------------------------------------- #
#  3. Hammering the button
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("after", ["success", "unknown"])
def test_07_ten_clicks_on_submit(after):
    script = [{"latency": 30}] if after == "success" else [{"latency": 250}]
    with Portal(cr=SlowCR(script=script * 12)) as h:
        statuses = [h.submit().status_code for _ in range(10)]
        check(f"07 ten submit clicks ({after})", h)
        if FIX:
            assert statuses[0] == 202 and set(statuses[1:]) == {409}


@pytest.mark.parametrize("clickers", [2, 5])
def test_08_concurrent_submits_from_several_tabs(clickers):
    """Every request is inside the balance read before any has claimed."""
    with Portal(cr=SlowCR(script=[{"latency": 30}] * 8)) as h:
        barrier = threading.Barrier(clickers, timeout=5)

        def gate():
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass

        h.cr.on_call["/tpsi/enquireDepositAccount"] = gate
        codes = []

        def click():
            c = TestClient(h.http.app, raise_server_exceptions=False)
            codes.append(c.post("/tpsi/filings/f1/submit", headers=H,
                                json={"confirm": True}).status_code)

        threads = [threading.Thread(target=click) for _ in range(clickers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        check(f"08 {clickers} concurrent submits", h)
        if FIX:
            assert sorted(codes) == [202] + [409] * (clickers - 1)


def test_09_second_tab_clicks_submit_while_the_first_is_still_in_flight():
    """The operator, or a colleague on another screen, presses Submit while CR
    is still working on the first (the 25-56 s window)."""
    with Portal(cr=SlowCR(script=[{"latency": 90}] * 4)) as h:
        seen = {}

        def mid_flight():
            if "started" in seen:          # only the first call has a 'during'
                return
            seen["started"] = True
            seen["second_tab"] = h.submit().status_code
            seen["validate"] = h.validate().status_code
            seen["sign"] = h.sign().status_code

        h.cr.on_call[SUBMIT] = mid_flight
        h.submit()
        check("09 submit clicked during a slow in-flight submit", h)
        if FIX:
            assert seen["second_tab"] == 409


# --------------------------------------------------------------------------- #
#  4. Stale claim sweep (worker died mid-call)
# --------------------------------------------------------------------------- #

def _died_mid_call(age: int | str):
    """The state a worker's death leaves, with CR already holding the form.
    On master nothing is written before the CR call, so the row is `signed`;
    on the fix it is a `submitting` claim."""
    filing = ({"stage": "submitting", "submit_started_at": age if isinstance(age, str)
               else ago(age)} if FIX else {"stage": "signed"})
    cr = SlowCR(script=[{"latency": 30}] * 6)
    cr.lodged = 1                          # the dead worker's request arrived
    return seed(filing=filing), cr


@pytest.mark.parametrize("age", [60, STALE + 30], ids=["live-claim", "stale-claim"])
def test_10_stale_claim_sweep_then_every_door(age):
    store, cr = _died_mid_call(age)
    with Portal(store, cr) as h:
        polled = h.poll()
        if FIX:
            expect = "submitting" if age < STALE else "submission_unknown"
            assert polled.json()["stage"] == expect
        h.hammer(3)
        h.http.post("/tpsi/filings/prepare", headers=H,
                    json={"entity_id": "e1", "nar1_case_id": "c1"})
        check(f"10 died mid-call, claim {age}s old", h)


def test_11_resolve_lodged_after_a_sweep_closes_it_without_a_second_send():
    store, cr = _died_mid_call(CLAIMED)
    with Portal(store, cr) as h:
        h.poll()                                   # sweeps to unknown
        cr.answers["/tpsi/docStatusEnquiry"] = doc_status_reply(
            submission_date="23/10/2026")
        done = h.resolve(outcome="lodged", receipt=RECEIPT_IN)
        h.hammer(3)
        check("11 sweep then resolve 'lodged'", h)
        if FIX:
            assert done.status_code == 200, done.text
            row = h.store.get("tpsi_filings", "f1")
            assert row["stage"] == "submitted"
            assert row["receipt"]["source"] == "operator_after_timeout"
            assert cr.count("docStatusEnquiry") == 1   # verified with CR, free


@fix_only
def test_12_late_receipt_after_the_sweep_is_kept_and_nothing_is_resent():
    """A call that outlives its bound (a dripping reply): the sweep and an
    honest 'not lodged' both happen while CR is still answering, then the
    receipt arrives. It must be stored, and CR must not be reached again."""
    with Portal(cr=SlowCR(script=[{"latency": 30}] * 4)) as h:
        def during():
            if FIX:
                # The call has outlived its bound. The claim's own timestamp is
                # left alone (a late receipt is keyed to it); only the clock
                # the sweep and the 'not lodged' gate read is wound forward.
                with patch.object(filings, "STALE_CLAIM_SECONDS", -1):
                    assert h.poll().json()["stage"] == "submission_unknown"
                    assert h.resolve(outcome="not_lodged",
                                     checked_cr=True).status_code == 200
                h.validate(); h.sign()

        h.cr.on_call[SUBMIT] = during
        h.submit()
        check("12 late receipt after sweep + not_lodged", h)
        if FIX:
            row = h.store.get("tpsi_filings", "f1")
            assert row["stage"] == "submitted"
            assert row["receipt"]["caseNo"] == "180256934", "late receipt lost"


# --------------------------------------------------------------------------- #
#  5. Permission and audit spot-checks (fix only)
# --------------------------------------------------------------------------- #

STAFF = {"id": "u2", "display_name": "Staff", "role_name": "staff",
         "role_id": "role-x", "email": "s@zenexflow.com"}


@fix_only
@pytest.mark.parametrize("path,body", [
    ("/tpsi/filings/f1/submit", {"confirm": True}),
    ("/tpsi/filings/f1/resolve", {"outcome": "not_lodged", "checked_cr": True}),
])
def test_20_no_token_is_refused(path, body):
    with Portal(seed(filing={"stage": "submission_unknown",
                             "submit_started_at": CLAIMED})) as h:
        r = TestClient(h.http.app, raise_server_exceptions=False).post(path, json=body)
        record(f"20 no token {path}", h.cr.lodged, 0)
        assert r.status_code in (401, 403), r.status_code
        assert h.cr.calls == []


@fix_only
@pytest.mark.parametrize("granted", [{"read"}, {"read", "write"}, set()],
                         ids=["read", "read+write", "none"])
@pytest.mark.parametrize("path,body", [
    ("/tpsi/filings/f1/submit", {"confirm": True}),
    ("/tpsi/filings/f1/resolve", {"outcome": "not_lodged", "checked_cr": True}),
])
def test_21_without_tpsi_submit_is_403(path, body, granted):
    with Portal(seed(filing={"stage": "submission_unknown",
                             "submit_started_at": CLAIMED}), user=STAFF) as h, \
            patch("middleware.auth._permissions_for", return_value=granted):
        r = h.http.post(path, headers=H, json=body)
        assert r.status_code == 403
        assert h.cr.calls == []
        assert h.stage() == "submission_unknown"


@fix_only
def test_22_tpsi_submit_alone_is_enough_and_is_audited():
    with Portal(seed(filing={"stage": "signed"}), user=STAFF) as h, \
            patch("middleware.auth._permissions_for", return_value={"submit"}):
        assert h.submit().status_code == 202
        assert h.cr.lodged == 1


@fix_only
def test_23_audit_trail_of_a_timeout_and_of_each_resolution():
    with Portal(cr=SlowCR(script=[{"latency": 250}] * 3)) as h:
        h.submit()
        assert h.actions() == ["TPSI_SUBMISSION_ATTEMPTED",
                               "TPSI_SUBMISSION_UNKNOWN"]
        unk = h.events[-1]
        assert {"reason", "waited_seconds"} <= set(unk["metadata"])
        h.store.get("tpsi_filings", "f1")["submit_started_at"] = ago(STALE + 30)
        assert h.resolve(outcome="not_lodged", checked_cr=True).status_code == 200
        res = h.events[-1]
        assert res["action_type"] == "TPSI_SUBMISSION_RESOLVED"
        assert res["after_state"] == {"outcome": "not_lodged"}
        assert res["user_id"] == SUPER["id"]
    # no credential in any row
    blob = repr(h.events).lower()
    assert "password" not in blob and "'pw'" not in blob


@fix_only
def test_24_lodged_resolution_is_audited_with_the_receipt():
    with Portal(seed(filing={"stage": "submission_unknown",
                             "submit_started_at": CLAIMED})) as h:
        assert h.resolve(outcome="lodged", receipt=RECEIPT_IN).status_code == 200
        res = [e for e in h.events if e["action_type"] == "TPSI_SUBMISSION_RESOLVED"]
        assert len(res) == 1
        assert res[0]["after_state"]["outcome"] == "lodged"
        assert res[0]["after_state"]["receipt"]["caseNo"] == "180256934"


@fix_only
def test_25_audit_codes_are_seeded_by_migration_056_for_g_flowdesk():
    import pathlib
    import re

    text = (pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
            ).glob("056*.py")
    src = next(text).read_text()
    for code in ("TPSI_SUBMISSION_UNKNOWN", "TPSI_SUBMISSION_RESOLVED"):
        assert code in src
    assert "g_flowdesk" in src
    assert re.search(r'revision\s*=\s*"056"', src)
    assert re.search(r'down_revision\s*=\s*"051"', src)
