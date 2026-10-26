"""A whole portal in front of a fake Companies Registry, for the submit tests.

The PROD incident of 2026-10-26 was not one function returning the wrong
value. It was a SEQUENCE: submit -> CR does not answer in time -> the screen
says CR refused it -> the operator re-validates, re-signs and submits again ->
CR receives the same annual return twice and charges twice. A test of any one
of those calls in isolation passed on the code that did it.

So this drives the real routes, the real `filings` service and the real
`TpsiClient` — the only fakes are at the two edges the portal does not own:
Supabase (`FakeStore`, which keeps real rows) and CR itself (an
`httpx.MockTransport` that records every request and can be told to time out,
drop the connection, or answer with anything). What reaches the transport is
what would have reached CR.

Nothing here can reach a real service: every `get_supabase` the path reads is
pointed at the store, `DATABASE_URL` is removed so the token lock never opens a
connection, and CR's host is never resolved because the transport answers
first.
"""
import os
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from services.tpsi import fees
from tests.tpsi.fake_store import FakeStore

CR_NS = "http://interfaces.service.webservice.icris3e.cr.gov.hk/"

SUPER = {"id": "u1", "display_name": "Levi", "role_name": "super_admin",
         "role_id": "role-sa", "email": "levi@zenexflow.com"}
H = {"Authorization": "Bearer tok"}

TODAY = fees._hk_today()

#: Enough of a return for the fee and the return-date gate: a year, and a share
#: class (CR's section (A) tariff). Incorporated TODAY, so the return date is
#: today and the return is on time on whatever day the suite runs.
FORM = (f"<cr:yearAnnualReturn>{TODAY.year}</cr:yearAnnualReturn>"
        "<cr:shareCapitals><cr:shareCapital>"
        "<cr:clsOfShares>Ordinary</cr:clsOfShares>"
        "</cr:shareCapital></cr:shareCapitals>")

VALIDATED = (
    f'<cr:submission xmlns:cr="{CR_NS}"><cr:EForm id="eForm">'
    f'<cr:formModel id="formData">{FORM}</cr:formModel></cr:EForm>'
    '<cr:EFormSignatures><cr:Signature id="CR"/></cr:EFormSignatures>'
    "</cr:submission>"
)

SIGNED = VALIDATED.replace("</cr:EFormSignatures>",
                           "<cr:PinSign/></cr:EFormSignatures>")


def envelope(body: str) -> bytes:
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{body}</soap:Body></soap:Envelope>"
    ).encode()


RECEIPT = envelope(
    f'<cr:submitFormResponse xmlns:cr="{CR_NS}"><cr:receipt>'
    "<cr:accNo>ACC</cr:accNo><cr:brNo>12345678</cr:brNo>"
    "<cr:caseNo>180256934</cr:caseNo>"
    "<cr:engCoyName>FIXTURE LIMITED</cr:engCoyName>"
    "<cr:pymtNo>5010475972</cr:pymtNo><cr:pymtRefNo>733037536</cr:pymtRefNo>"
    "<cr:pymtMtd>Deduct from Account</cr:pymtMtd>"
    "<cr:transactionDate>28/06/2026</cr:transactionDate>"
    "<cr:transactionTime>13:36:44</cr:transactionTime>"
    "<cr:totalAmount>105.0</cr:totalAmount>"
    "<cr:paymentRcptList><amtChrg>105.0</amtChrg><docShtFrm>NAR1</docShtFrm>"
    "<rcptNo>D77000078859</rcptNo><revCode>118</revCode>"
    "<revDesc>Annual return fee</revDesc></cr:paymentRcptList>"
    "</cr:receipt></cr:submitFormResponse>"
)

#: CR's business refusal: a SOAP fault carrying fault beans, as HTTP 500.
FAULT_BEANS = envelope(
    "<soap:Fault><faultcode>soap:Server</faultcode><faultstring>err</faultstring>"
    '<detail><cr:EfilingWebServiceError xmlns:cr="http://x/">'
    "<webServiceFaultBeans><faultCode>ERR_MSG_X</faultCode>"
    "<faultString>Deposit account suspended</faultString>"
    "</webServiceFaultBeans></cr:EfilingWebServiceError></detail></soap:Fault>"
)


def doc_status_reply(br_no="12345678", case_no="180256934",
                     document_name="NAR1", submission_date="23/10/2026") -> bytes:
    return envelope(
        f'<cr:enquireDocStatusResponse xmlns:cr="{CR_NS}"><cr:result>'
        "<cr:documentList><cr:document>"
        f"<cr:caseNo>{case_no}</cr:caseNo><cr:brno>{br_no}</cr:brno>"
        f"<cr:documentName>{document_name}</cr:documentName>"
        f"<cr:submissionDate>{submission_date}</cr:submissionDate>"
        "<cr:documentStatus>Lodged</cr:documentStatus>"
        "</cr:document></cr:documentList></cr:result>"
        "</cr:enquireDocStatusResponse>"
    )


CASE_NOT_FOUND = envelope(
    "<soap:Fault><faultcode>soap:Server</faultcode><faultstring>err</faultstring>"
    '<detail><cr:EfilingWebServiceError xmlns:cr="http://x/">'
    "<webServiceFaultBeans><faultCode>ERR</faultCode>"
    "<faultString>Case no does not exist.</faultString>"
    "</webServiceFaultBeans></cr:EfilingWebServiceError></detail></soap:Fault>"
)


@dataclass
class FakeCR:
    """CR, as far as the portal can tell. Answers by URL path.

    `answers[path]` is either bytes/an httpx.Response to return, or an
    exception instance to raise from inside the transport — which is exactly
    where httpx raises a real ReadTimeout.
    """
    answers: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)
    timeouts: dict = field(default_factory=dict)
    on_call: dict = field(default_factory=dict)

    def __post_init__(self):
        self.answers = {
            "/oauth/token.do": httpx.Response(
                200, json={"access_token": "TOKEN", "expires_in": 1800}),
            "/tpsi/enquireDepositAccount": envelope(
                f'<cr:enquireDepositAccountResponse xmlns:cr="{CR_NS}">'
                "<cr:accountBalance>999999</cr:accountBalance>"
                "</cr:enquireDepositAccountResponse>"),
            "/tpsi/validateFormNar1": envelope(
                f'<cr:validateFormResponse xmlns:cr="{CR_NS}">'
                f"{VALIDATED}</cr:validateFormResponse>"),
            "/tpsi/verifyPinSigningNar1": envelope(
                f'<cr:verifyPinSigningResponse xmlns:cr="{CR_NS}">'
                "<cr:result>Pin Signature(s) Verified Successfully.</cr:result>"
                "</cr:verifyPinSigningResponse>"),
            "/tpsi/submitFormNar1": RECEIPT,
            "/tpsi/docStatusEnquiry": doc_status_reply(),
            "/oauth/revoke.do": httpx.Response(200, json={}),
            **self.answers,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/ICRIS3EF")
        self.calls.append(path)
        self.timeouts.setdefault(path, []).append(
            request.extensions.get("timeout", {}).get("read"))
        if path in self.on_call:
            self.on_call[path]()
        answer = self.answers[path]
        if isinstance(answer, list):
            # A sequence: one answer per call, the last one repeating.
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, content=answer)

    def count(self, operation: str) -> int:
        return sum(1 for p in self.calls if p.endswith(operation))

    def client(self):
        from services.tpsi.client import TpsiClient

        c = TpsiClient("PRESENTER", "pw")
        c._transport = httpx.MockTransport(self.handler)
        return c


def seed(**over) -> FakeStore:
    """One company, one approved case, one SIGNED filing ready to submit."""
    filing = {
        "id": "f1", "entity_id": "e1", "nar1_case_id": "c1",
        "form_code": "Nar1", "stage": "signed",
        "request_xml": FORM, "validated_xml": VALIDATED, "signed_xml": SIGNED,
        "form_filing_id": None, "presenter_user_id": "u1",
        "created_at": "2026-10-20T01:00:00+00:00",
        **over.pop("filing", {}),
    }
    case = {
        "id": "c1", "case_no": "NAR-2026-0319", "entity_id": "e1",
        "nar1_type": "annual_return", "signing_method": "esign",
        "verification_sent_at": "2026-10-01T01:00:00+00:00",
        "client_approved": True, "client_response_at": "2026-10-02T01:00:00+00:00",
        "closed_at": None, "manual_receipt": None, "manual_submitted_at": None,
        "ar_period_year": TODAY.year,
        **over.pop("case", {}),
    }
    entity = {"id": "e1", "company_name": "FIXTURE LIMITED",
              "br_number": "12345678", "company_type": "P",
              "incorporation_date": TODAY.isoformat()}
    return FakeStore({
        "tpsi_filings": [filing, *over.pop("more_filings", [])],
        "nar1_cases": [case],
        "entities": [entity],
        "nar1_case_registry": [{"id": "c1", "company_name": "FIXTURE LIMITED",
                                "br_number": "12345678", "entity_id": "e1"}],
    })


def ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class Harness:
    """The portal, wired to `FakeStore` and `FakeCR`. Use as a context manager."""

    def __init__(self, store: FakeStore | None = None, cr: FakeCR | None = None,
                 user: dict | None = None):
        self.store = store or seed()
        self.cr = cr or FakeCR()
        self.user = user or SUPER
        self.events: list[dict] = []
        self.tpsi = self.cr.client()
        self._stack = ExitStack()

    def __enter__(self):
        from main import app

        async def record(**kwargs):
            self.events.append(kwargs)

        shared = SimpleNamespace(account_id="PRESENTER", tpsi_password="pw",
                                 deposit_account_no="ACC")
        sb = lambda: self.store  # noqa: E731
        # The token lock opens a Postgres connection when DATABASE_URL is set.
        self._stack.enter_context(patch.dict(os.environ))
        os.environ.pop("DATABASE_URL", None)
        for target, value in [
            ("services.tpsi.filings.get_supabase", sb),
            ("services.nar1_cases.get_supabase", sb),
            ("routers.tpsi.get_supabase", sb),
            ("routers.cases.get_supabase", sb),
            ("services.tpsi.audit_context.get_supabase", sb),
            ("routers.tpsi.client_for", lambda *a, **k: self.tpsi),
            ("routers.tpsi.shared_credentials.load_for_use", lambda: shared),
            ("services.tpsi.shared_credentials.deposit_account_no", lambda: "ACC"),
            # `audit_auth` persists CR's password-expiry hint after a real login.
            ("services.tpsi.shared_credentials.record_password_expiry",
             lambda *_a: None),
            ("routers.tpsi.credentials.load_eservice", lambda _u: ("USERID", "pw")),
            ("services.tpsi.crypto.build_pin_sign", lambda *a, **k: "<cr:PinSign/>"),
            ("services.tpsi.crypto.signing_public_key_pem", lambda *_a: "pem"),
            ("services.tpsi.drift.current_xml_for",
             lambda filing: filing.get("request_xml") or ""),
            ("services.nar1_approvals.supersede_outstanding", lambda *a, **k: 0),
            ("middleware.auth._resolve_user", lambda *a, **k: self.user),
        ]:
            self._stack.enter_context(patch(target, value))
        # `services.audit_service.log_event` too: `filings.settle_stale_claim`
        # imports it at call time, so the module attribute is the seam.
        for target in ("routers.tpsi.log_event", "routers.cases.log_event",
                       "services.audit_service.log_event"):
            self._stack.enter_context(patch(target, side_effect=record))
        self.http = TestClient(app, raise_server_exceptions=False)
        return self

    def __exit__(self, *exc):
        self._stack.close()

    # ---- the operator's buttons ------------------------------------------
    def submit(self):
        return self.http.post("/tpsi/filings/f1/submit", headers=H,
                              json={"confirm": True})

    def validate(self):
        return self.http.post("/tpsi/filings/f1/validate", headers=H)

    def sign(self):
        return self.http.post("/tpsi/filings/f1/sign", headers=H, json={})

    def stage(self, filing_id="f1") -> str:
        return self.store.get("tpsi_filings", filing_id)["stage"]

    def actions(self) -> list[str]:
        return [e.get("action_type") for e in self.events]
