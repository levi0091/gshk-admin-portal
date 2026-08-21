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
  - Non-production REFUSES to send unless EMAIL_REDIRECT_TO names the mailbox
    everything goes to instead.
  - Production REFUSES to send when EMAIL_REDIRECT_TO is set, because the
    alternative is every client silently receiving nothing while the portal
    reports each send as successful.

Both crossings are refused outright rather than warned about, and both are
refused BEFORE any HTTP call.

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
from functools import lru_cache

import httpx

#: Resend's send endpoint.
RESEND_ENDPOINT = "https://api.resend.com/emails"

#: A hung Resend must not hang the request thread holding the case open — the
#: admin would never learn whether the client was mailed.
TIMEOUT_SECONDS = 15.0

#: Levi 2026-08-16, superseding the earlier Gmail decision. SPF/DKIM only align
#: on a domain the sender controls, and GSHK controls getstarted.hk.
DEFAULT_FROM = "no-reply@getstarted.hk"


class EmailError(RuntimeError):
    """Resend refused the message, or the transport failed.

    Never carries the API key, the request object, or a chained exception that
    could reach either.
    """


class EmailConfig:
    __slots__ = ("api_key", "sender", "is_production", "redirect_to")

    def __init__(self, api_key, sender, is_production, redirect_to):
        self.api_key = api_key
        self.sender = sender
        self.is_production = is_production
        self.redirect_to = redirect_to


@lru_cache(maxsize=1)
def get_email_config() -> EmailConfig:
    """Resolve and VALIDATE the mail configuration.

    Cached, so `cache_clear()` is the way to pick up an env change (tests do
    exactly that). Every refusal below happens here, which is what keeps them
    ahead of the HTTP call rather than beside it.
    """
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not api_key:
        # Name only, never the value — this message reaches logs.
        raise RuntimeError(
            "RESEND_API_KEY is not set; refusing to send mail without it"
        )

    # Unset APP_ENV is non-production ON PURPOSE. See the module docstring.
    is_production = (os.environ.get("APP_ENV") or "").strip().lower() == "prod"
    redirect_to = (os.environ.get("EMAIL_REDIRECT_TO") or "").strip() or None

    if not is_production and not redirect_to:
        raise RuntimeError(
            "EMAIL_REDIRECT_TO must name a mailbox on a non-production "
            "deployment: APP_ENV is not 'prod', and this database carries real "
            "client addresses. Set EMAIL_REDIRECT_TO, or set APP_ENV=prod if "
            "this really is production."
        )
    if is_production and redirect_to:
        raise RuntimeError(
            "EMAIL_REDIRECT_TO is set while APP_ENV=prod. Every client would "
            "silently receive nothing while the portal reported each send as "
            "successful. Unset EMAIL_REDIRECT_TO on production."
        )

    sender = (os.environ.get("VERIFICATION_FROM") or "").strip() or DEFAULT_FROM
    return EmailConfig(api_key, sender, is_production, redirect_to)


def _scrub(text: str, api_key: str) -> str:
    """Last line of defence. The key should never reach here; if it does, it
    stops here rather than in a log aggregator."""
    return text.replace(api_key, "***") if api_key else text


def send(*, to: str, subject: str, html: str, attachments=None) -> dict:
    """Send one message. Returns what was actually delivered, and to whom.

    `attachments` is a list of (filename, bytes). The caller keeps hold of the
    bytes; nothing here writes them anywhere.

    The result distinguishes `to` (where it went) from `intended_to` (who it was
    for) so a redirected non-production send can never be mistaken for a real
    one by whatever records it.
    """
    config = get_email_config()

    intended_to = to
    redirected = False
    if config.redirect_to:
        # Say who it was for, in both the subject and the body: a redirected
        # mailbox fills up with messages that are otherwise indistinguishable.
        subject = f"[DEV -> {intended_to}] {subject}"
        html = (
            f'<p style="background:#FEF0EB;padding:8px;border-radius:4px">'
            f"Non-production send. Intended recipient: "
            f"<strong>{_html.escape(intended_to)}</strong></p>{html}"
        )
        to = config.redirect_to
        redirected = True

    payload = {
        "from": config.sender,
        "to": [to],
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
        "to": to,
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
