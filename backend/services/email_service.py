"""Resend transport for workflow mail (BE-3).

Resend's HTTP API over httpx rather than the `resend` package: httpx is already
a dependency, the request shape stays visible in review, and this repo already
made the same call for Supabase (whose Python client rejected the new key
format).

*** THE NON-PRODUCTION INTERLOCK ***
DEV's Supabase is a copy of Viewpoint and carries REAL client and director email
addresses, while `backend/.env` holds a LIVE Resend key. A DEV deployment is
therefore one button away from mailing a real client a statutory form. So the
same shape as the TPSI env interlock applies here:

  - APP_ENV decides, and an UNSET APP_ENV is treated as non-production. A
    missing variable is not a licence to mail strangers.
  - Non-production mail goes to TEST_RECIPIENTS and NOWHERE ELSE. That list is
    a constant in this module, not configuration: Levi 2026-08-30 asked that it
    be "programatically impossible for a client to receive an email from a test
    account", and a setting that can be unset, misspelt, or pointed at a client
    by an accident of deployment is not that. `EMAIL_REDIRECT_TO` used to serve
    this purpose and has been REMOVED; setting it again does nothing at all.
  - Production is unaffected and still reaches the real client. The interlock
    leaking into production would mean every client silently receiving nothing
    while the portal reported each send as successful.

The substitution happens inside `send()`, below every caller, and a second
assertion re-checks the outgoing list immediately before the HTTP call. The
first is the mechanism; the second catches a future edit that reorders it.

The Client Verification screen still shows, and still lets an operator pick,
the REAL director addresses -- that fan-out is the thing being tested. Only the
destination changes, and the screen says so in as many words.

*** THE KEY MUST NOT LEAK ***
httpx exceptions carry the request, and the request carries the Authorization
header. So a transport failure is re-raised as a bare EmailError with no
__cause__ and no __context__ — raised outside the `except` block, because
`raise ... from None` clears __cause__ but leaves __context__ populated. Every
message that can reach a log is scrubbed of the key as a second guard.
"""
import base64
import html as _html
import os
import sys
from functools import lru_cache

import httpx

from services import app_env

#: Resend's send endpoint.
RESEND_ENDPOINT = "https://api.resend.com/emails"

#: WHERE ALL NON-PRODUCTION MAIL GOES. Levi 2026-08-30.
#:
#: Hardcoded, and deliberately not readable from the environment. DEV's Supabase
#: is a copy of Viewpoint and carries 4,398 real director addresses; the ask was
#: that it be *impossible*, not merely configured, for one of them to be mailed
#: from a test deployment. A tuple rather than a list so it cannot be mutated in
#: place by a caller that got hold of it.
TEST_RECIPIENTS = (
    "levi@zenexflow.com",
    "roy@zenexflow.com",
    "brian@getstarted.hk",
    "vanis@getstarted.hk",
)

#: A hung Resend must not hang the request thread holding the case open — the
#: admin would never learn whether the client was mailed.
TIMEOUT_SECONDS = 15.0

#: Levi 2026-08-16. SPF/DKIM only align on a domain the sender controls, and
#: GSHK controls getstarted.hk — which is what makes Resend viable here.
DEFAULT_FROM = "no-reply@getstarted.hk"


class EmailError(RuntimeError):
    """Resend refused the message, or the transport failed.

    Never carries the API key, the request object, or a chained exception that
    could reach either.
    """


#: `EMAIL_TRANSPORT=console` writes the message to stderr and delivers nothing.
#: It exists because Resend is not usable yet on this project (the key in
#: `.env` is rejected by Resend with "API key is invalid"), and without it the
#: entire client-verification half of the NAR1 workflow is unreachable on DEV --
#: `verification_sent_at` is only stamped after a successful send, so nothing
#: can be driven to Awaiting Client, Signing or Submission.
#:
#: IT IS A LIE ABOUT DELIVERY, AND IS TREATED AS ONE. It is refused outright on
#: production (below), it must be asked for by name -- no default, no inference
#: from a missing key -- and every result it returns carries
#: `transport="console"`, which the router writes into the audit trail. A row
#: saying a client was told, when nobody was, is the single worst thing this
#: module can produce; the flag is what stops that row existing.
CONSOLE_TRANSPORT = "console"


class EmailConfig:
    __slots__ = ("api_key", "sender", "is_production", "transport")

    def __init__(self, api_key, sender, is_production, transport="resend"):
        self.api_key = api_key
        self.sender = sender
        self.is_production = is_production
        self.transport = transport


def _apply_test_recipient_lock(recipients, is_production):
    """Substitute the fixed test list on any non-production deployment.

    Returns `(recipients, redirected)`. Factored out of `send()` so the guard
    that follows it there can be tested independently of the mechanism -- see
    tests/test_email_test_recipients.py, which stubs this out to prove the
    guard fires on its own.
    """
    if is_production:
        return recipients, False
    return list(TEST_RECIPIENTS), True


@lru_cache(maxsize=1)
def get_email_config() -> EmailConfig:
    """Resolve and VALIDATE the mail configuration.

    Cached, so `cache_clear()` is the way to pick up an env change (tests do
    exactly that). Every refusal below happens here, which is what keeps them
    ahead of the HTTP call rather than beside it.
    """
    # Unset APP_ENV is non-production ON PURPOSE. See the module docstring.
    # One shared reading of APP_ENV, so this can never disagree with the TEST
    # badge in the header or with the TPSI environment interlock.
    is_production = app_env.is_production()
    transport = (os.environ.get("EMAIL_TRANSPORT") or "").strip().lower() or "resend"

    if transport == CONSOLE_TRANSPORT:
        if is_production:
            raise RuntimeError(
                "EMAIL_TRANSPORT=console while APP_ENV=prod. Every client would "
                "silently receive nothing while the portal reported each send "
                "as successful. Unset EMAIL_TRANSPORT on production."
            )
        # No API key and no redirect mailbox are required: nothing leaves the
        # process, so there is no key to protect and nowhere to redirect to.
        sender = (os.environ.get("VERIFICATION_FROM") or "").strip() or DEFAULT_FROM
        return EmailConfig("", sender, False, CONSOLE_TRANSPORT)
    if transport != "resend":
        raise RuntimeError(
            f"EMAIL_TRANSPORT={transport!r} is not a transport this build "
            f"knows; use 'resend', or 'console' on a non-production deployment"
        )

    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not api_key:
        # Name only, never the value — this message reaches logs.
        raise RuntimeError(
            "RESEND_API_KEY is not set; refusing to send mail without it"
        )

    # There is no non-production refusal any more. A safe destination is
    # compiled in, so a dev deployment needs nothing configured to send mail.
    sender = (os.environ.get("VERIFICATION_FROM") or "").strip() or DEFAULT_FROM
    return EmailConfig(api_key, sender, is_production)


def _scrub(text: str, api_key: str) -> str:
    """Last line of defence. The key should never reach here; if it does, it
    stops here rather than in a log aggregator."""
    return text.replace(api_key, "***") if api_key else text


def send(*, to, subject: str, html: str, attachments=None) -> dict:
    """Send one message to one or more recipients. Returns who actually got it.

    `to` is an address or a sequence of them — a board of three directors is one
    message with three recipients, not three messages: the client sees the same
    thread, and one Resend failure cannot leave two directors informed and the
    third not.

    `attachments` is a list of (filename, bytes). The caller keeps hold of the
    bytes; nothing here writes them anywhere.

    `to` and `intended_to` come back as LISTS, always — a caller must not have
    to guess the shape from the count. They differ when a non-production send is
    redirected, so a redirect can never be mistaken for a real delivery by
    whatever records it.
    """
    config = get_email_config()

    recipients = [to] if isinstance(to, str) else [str(a) for a in to]
    recipients = [a.strip() for a in recipients if (a or "").strip()]
    if not recipients:
        # An empty list would otherwise become a 422 from Resend, spending a
        # round trip to learn something already knowable here.
        raise EmailError("no recipient was given for this message")

    intended_to = list(recipients)
    redirected = False

    if config.transport == CONSOLE_TRANSPORT:
        # Ahead of the redirect block: there is no mailbox to redirect to, and
        # ahead of any HTTP call, because there is not going to be one.
        print(
            f"[email_service] NOT SENT (EMAIL_TRANSPORT=console) — "
            f"to={intended_to} subject={subject!r} "
            f"attachments={[name for name, _ in (attachments or [])]}",
            file=sys.stderr, flush=True,
        )
        return {
            "id": None,
            "to": intended_to,
            "intended_to": intended_to,
            "redirected": False,
            # The whole point. A caller that records this as a delivery has to
            # ignore a key that is right there saying it was not one.
            "transport": CONSOLE_TRANSPORT,
        }

    recipients, redirected = _apply_test_recipient_lock(
        recipients, config.is_production
    )
    if redirected:
        # Say who it was really for, in both the subject and the body: four
        # people share these mailboxes across every test case, and a message
        # that does not name the directors it stood in for is untestable noise.
        # ALL of them — naming only the first hides the fan-out being tested.
        joined = ", ".join(intended_to)
        subject = f"[TEST -> {joined}] {subject}"
        html = (
            f'<p style="background:#FEF0EB;padding:8px;border-radius:4px">'
            f"Test-environment send. NOT delivered to the client. Intended "
            f"recipient{'s' if len(intended_to) > 1 else ''}: "
            f"<strong>{_html.escape(joined)}</strong></p>{html}"
        )

    # Defence in depth, immediately before the only call that can deliver
    # anything. The substitution above is the mechanism; this is the assertion
    # that the mechanism ran. If a later edit reorders send() so a client
    # address survives to here on a non-production deployment, this raises
    # rather than mailing them.
    if not config.is_production and set(recipients) - set(TEST_RECIPIENTS):
        raise EmailError(
            "refusing to send: this is not a production deployment and the "
            "recipient list is not the fixed test list. That is a bug in "
            "email_service.send(), not a configuration problem."
        )

    payload = {
        "from": config.sender,
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = [
            {"filename": name,
             "content": base64.b64encode(content).decode("ascii")}
            for name, content in attachments
        ]

    # Transport errors are captured, not re-raised in place: raising inside the
    # `except` block would leave __context__ pointing at an httpx exception that
    # carries the request, and therefore the Authorization header.
    transport_failure = None
    response = None
    try:
        response = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {config.api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see above
        transport_failure = f"{type(exc).__name__}: {exc}"

    if transport_failure is not None:
        raise EmailError(
            "could not reach Resend: "
            + _scrub(transport_failure, config.api_key)
        )

    if response.status_code >= 400:
        try:
            body = response.json()
            detail = body.get("message") or body.get("error") or str(body)
        except Exception:  # noqa: BLE001 — a non-JSON error body is still an error
            detail = (getattr(response, "text", "") or "")[:500]
        raise EmailError(
            _scrub(f"Resend rejected the message ({response.status_code}): "
                   f"{detail}", config.api_key)
        )

    try:
        message_id = (response.json() or {}).get("id")
    except Exception:  # noqa: BLE001
        message_id = None

    return {
        "id": message_id,
        "to": recipients,
        "intended_to": intended_to,
        "redirected": redirected,
    }


def verification_email(case: dict, entity: dict) -> tuple[str, str]:
    """The client-verification message: subject and HTML body.

    Every interpolated value is escaped. Company names come out of the Viewpoint
    ETL, and an unescaped one lands in the client's mailbox as live markup.

    Carries NO credential and no link-borne secret — the client confirms by
    replying to GSHK, so there is nothing here to steal or replay.
    """
    company = (entity.get("company_name") or "").strip()
    case_no = (case.get("case_no") or "").strip()
    br_number = (entity.get("br_number") or "").strip()

    subject = (
        f"Annual Return for {company} — please confirm"
        if company else "Annual Return — please confirm"
    )

    # Built row by row so a missing value omits its row rather than rendering
    # the word "None" at a client.
    rows = []
    for label, value in (("Company", company),
                         ("Business Registration No.", br_number),
                         ("Case", case_no)):
        if value:
            rows.append(
                f'<tr><td style="padding:4px 12px 4px 0;color:#7C80A3">'
                f"{_html.escape(label)}</td>"
                f'<td style="padding:4px 0;color:#1A2050">'
                f"<strong>{_html.escape(value)}</strong></td></tr>"
            )
    table = (f'<table style="border-collapse:collapse;margin:16px 0">'
             f'{"".join(rows)}</table>') if rows else ""

    body = (
        '<div style="font-family:Outfit,Arial,sans-serif;color:#3A4060">'
        '<h2 style="color:#242C66;margin:0 0 12px">Annual Return — '
        "please confirm</h2>"
        "<p>The attached Annual Return has been prepared for filing with the "
        "Companies Registry. Please review the particulars and confirm they "
        "are correct.</p>"
        f"{table}"
        "<p>If anything needs changing, reply to this message describing the "
        "change and we will revise the form before it is filed.</p>"
        '<p style="color:#7C80A3;font-size:12px;margin-top:24px">Sent by Get '
        "Started HK Limited. Please do not reply to this address directly if "
        "you were given another contact.</p>"
        "</div>"
    )
    return subject, body
