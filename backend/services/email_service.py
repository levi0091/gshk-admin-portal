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


# EMAIL_TRANSPORT=console is GONE (Levi 2026-08-30). It wrote the message to
# stderr, delivered nothing, and reported success -- a lie about delivery,
# carried the whole way to the audit trail as `transport="console"` so nothing
# could mistake it for one. It existed for exactly one reason: RESEND_API_KEY
# held the literal placeholder `your-resend-api-key`, so no send could succeed
# and the entire client-facing half of the NAR1 workflow was unreachable
# (`verification_sent_at` is only stamped after a successful send).
#
# A real key is now in place and `getstarted.hk` is verified at Resend, so that
# reason is spent. Protecting clients was never this flag's job -- the
# TEST_RECIPIENTS lock above does that unconditionally, on every non-production
# deployment, whether or not anything is configured.
#
# Do not reintroduce it. If mail must be suppressed in some future environment,
# suppress it somewhere that cannot report a delivery that did not happen.


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


def _apply_test_cc_lock(cc, is_production):
    """A CC is a recipient, so the same rule binds it: on a non-production
    deployment it is DROPPED, not redirected.

    Dropped rather than substituted because the four addresses are already
    receiving the message as `to` -- copying them again would put the same
    mailbox on both lines. The case worker who would have been copied is one of
    the four on a test deployment; if they are not, they were never going to
    receive a test send in the first place, which is the interlock working.

    The intended list is still reported, so the audit trail records who a
    production send WOULD have copied.
    """
    if is_production:
        return cc, False
    return [], bool(cc)


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

    if transport != "resend":
        # 'console' lands here deliberately. A deployment that still sets it is
        # asking for mail to be silently swallowed, and the one thing that must
        # not happen is for that request to be quietly ignored while sends go
        # out for real -- so it stops here and names what changed.
        raise RuntimeError(
            f"EMAIL_TRANSPORT={transport!r} is not a transport this build "
            "knows; 'resend' is the only one. EMAIL_TRANSPORT=console was "
            "removed on 2026-08-30 once a working Resend key was in place — "
            "unset the variable. Mail from a non-production deployment is "
            "already confined to the fixed test recipients."
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


def _addresses(value) -> list[str]:
    """One address, a sequence of them, or nothing, as a clean list."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else [str(a) for a in value]
    return [a.strip() for a in items if (a or "").strip()]


def send(*, to, subject: str, html: str, attachments=None, cc=None,
         reply_to=None) -> dict:
    """Send one message to one or more recipients. Returns who actually got it.

    `to` is an address or a sequence of them — a board of three directors is one
    message with three recipients, not three messages: the client sees the same
    thread, and one Resend failure cannot leave two directors informed and the
    third not.

    `cc` is copied openly, and that is the point: the client can see which
    member of GSHK staff is handling their return, and can reply to all. It is
    subject to the same non-production lock as `to` — see _apply_test_cc_lock.

    `reply_to` steers the client's answer at a mailbox a human reads. The sender
    is `no-reply@`, so without this an email that ASKS for a reply would be
    asking for one nobody receives.

    `attachments` is a list of (filename, bytes). The caller keeps hold of the
    bytes; nothing here writes them anywhere.

    `to`, `intended_to`, `cc` and `intended_cc` come back as LISTS, always — a
    caller must not have to guess the shape from the count. The pairs differ
    when a non-production send is redirected, so a redirect can never be
    mistaken for a real delivery by whatever records it.
    """
    config = get_email_config()

    recipients = _addresses(to)
    if not recipients:
        # An empty list would otherwise become a 422 from Resend, spending a
        # round trip to learn something already knowable here.
        raise EmailError("no recipient was given for this message")

    copies = _addresses(cc)
    # A mailbox already on `to` must not also be on `cc`: some clients render
    # the same message twice, and every "reply all" then carries a duplicate.
    on_to = {a.casefold() for a in recipients}
    copies = [a for a in copies if a.casefold() not in on_to]

    intended_to = list(recipients)
    intended_cc = list(copies)
    redirected = False

    recipients, redirected = _apply_test_recipient_lock(
        recipients, config.is_production
    )
    copies, cc_dropped = _apply_test_cc_lock(copies, config.is_production)
    redirected = redirected or cc_dropped
    if redirected:
        # Say who it was really for, in both the subject and the body: four
        # people share these mailboxes across every test case, and a message
        # that does not name the directors it stood in for is untestable noise.
        # ALL of them — naming only the first hides the fan-out being tested.
        joined = ", ".join(intended_to)
        subject = f"[TEST -> {joined}] {subject}"
        html = _test_banner(intended_to, intended_cc) + html

    # Defence in depth, immediately before the only call that can deliver
    # anything. The substitution above is the mechanism; this is the assertion
    # that the mechanism ran. If a later edit reorders send() so a client
    # address survives to here on a non-production deployment, this raises
    # rather than mailing them. CC is checked too: a copied address is a
    # delivered address, and leaving it out of this check would leave the one
    # line of the message that the lock does not cover.
    if not config.is_production and (
        set(recipients) - set(TEST_RECIPIENTS) or copies
    ):
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
    if copies:
        payload["cc"] = copies
    if reply_to:
        # Resend accepts a string or a list; a list keeps one shape for callers.
        payload["reply_to"] = _addresses(reply_to)
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
        "cc": copies,
        "intended_cc": intended_cc,
        "redirected": redirected,
    }


# ---------------------------------------------------------------------------
# The client-facing message
#
# Written as tables with inline styles, and that is not laziness -- Outlook
# renders mail through Word, which has no flexbox, no grid, and no support for
# a <style> block it can be relied on to keep. Everything below is therefore
# nested <table>, explicit bgcolor, and hex colours.
#
# Outfit will NOT load in most mail clients, so the fallback stack IS the
# typography rather than a fallback: the design has to hold up set in Segoe UI
# and Helvetica, which is why it leans on scale, weight and letter-spacing
# rather than on the face.
#
# The design idea: a cover sheet clipped to a statutory form. The masthead
# carries the form designation and the company the way Form NAR1 itself does,
# and the particulars sit in a ruled ledger echoing the form's boxed fields --
# the reader has been asked to CHECK particulars, so showing them in the shape
# they will meet on the form makes the check natural instead of decorative.
#
# There is deliberately NO action button. Nothing here is clickable: the client
# confirms by replying, and a button that only opened a mail composer would be
# dressing up the ask as something it is not.
# ---------------------------------------------------------------------------

#: Brand tokens, verbatim from the repo's design system. Named here so the
#: template below reads as design rather than as a wall of hex.
_INDIGO = "#242C66"
_CARROT = "#F36C32"
_GROUND = "#F5F6FB"
_SHEET = "#FFFFFF"
_T_HEAD = "#1A2050"
_T_BODY = "#3A4060"
_T_MUTED = "#7C80A3"
_BORDER = "#E2E4ED"
#: The only colour NOT in the token list: a light indigo for text on the
#: masthead. Carrot on indigo measures 4.34:1, which fails AA for text this
#: small, so the accent is spent once -- on the rule beside the ask -- and the
#: masthead eyebrow gets a tint that clears 5.9:1 instead.
_ON_INDIGO = "#A9AECF"

_FONT = "'Outfit','Segoe UI',Roboto,Helvetica,Arial,sans-serif"

#: 11px, uppercase, tracked. One utility role, used for every label so the
#: ledger and the ask read as the same system.
_LABEL = (f"font-family:{_FONT};font-size:11px;font-weight:600;"
          f"letter-spacing:0.09em;text-transform:uppercase;color:{_T_MUTED};")


def _ledger_row(label: str, value: str, first: bool) -> str:
    """One boxed particular: tracked label over the value, hairline above."""
    rule = "" if first else f"border-top:1px solid {_BORDER};"
    return (
        f'<tr><td style="padding:{"12px" if first else "13px"} 18px 13px;'
        f'{rule}">'
        f'<div style="{_LABEL}padding-bottom:3px">{_html.escape(label)}</div>'
        f'<div style="font-family:{_FONT};font-size:15px;font-weight:600;'
        f'color:{_T_HEAD};line-height:1.35">{_html.escape(value)}</div>'
        f"</td></tr>"
    )


def verification_email(case: dict, entity: dict,
                       attachment_name: str | None = None) -> tuple[str, str]:
    """The client-verification message: subject and HTML body.

    Every interpolated value is escaped. Company names come out of the Viewpoint
    ETL, and an unescaped one lands in the client's mailbox as live markup.

    Carries NO credential, no link and no link-borne secret — the client
    confirms by replying, so there is nothing here to steal, replay, or mistake
    for a phishing link in a message that asks about their company's filings.
    """
    company = (entity.get("company_name") or "").strip()
    case_no = (case.get("case_no") or "").strip()
    br_number = (entity.get("br_number") or "").strip()
    period = str(case.get("ar_period_year") or "").strip()

    subject = (
        f"Annual Return for {company} — please confirm"
        if company else "Annual Return — please confirm"
    )

    # Built row by row so a missing value omits its row rather than rendering
    # the word "None" at a client. The company is NOT here: it is the masthead,
    # and repeating it would be one element doing two jobs.
    pairs = [("Business Registration No.", br_number),
             ("Return period", period),
             ("Our reference", case_no)]
    if not company:
        # Degenerate case only. Without a masthead name the reader has nothing
        # telling them which company this concerns, so the ledger takes it back.
        pairs.insert(0, ("Company", company))
    rows = [_ledger_row(label, value, i == 0)
            for i, (label, value) in enumerate([p for p in pairs if p[1]])]
    ledger = (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" style="border-collapse:separate;'
        f'border:1px solid {_BORDER};border-radius:8px;margin:26px 0 28px">'
        f'{"".join(rows)}</table>'
    ) if rows else ""

    attached = ""
    if attachment_name:
        attached = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" style="margin:26px 0 0"><tr>'
            f'<td style="border:1px solid {_BORDER};border-radius:6px;'
            f'padding:10px 14px;background:{_GROUND};font-family:{_FONT};'
            f'font-size:13px;color:{_T_BODY}">'
            f'<span style="{_LABEL}">Attached</span>&nbsp;&nbsp;'
            f'<span style="font-weight:600;color:{_T_HEAD}">'
            f"{_html.escape(attachment_name)}</span>"
            f'<span style="color:{_T_MUTED}"> — Form NAR1 with Schedule 1'
            f"</span></td></tr></table>"
        )

    body = (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" bgcolor="{_GROUND}" '
        f'style="background:{_GROUND};margin:0;padding:0">'
        f'<tr><td align="center" style="padding:28px 12px">'

        f'<table role="presentation" width="600" cellpadding="0" '
        f'cellspacing="0" border="0" style="width:600px;max-width:600px;'
        f'border-collapse:separate;border-radius:10px;overflow:hidden;'
        f'border:1px solid {_BORDER}">'

        # Masthead — the form designation and the company it concerns, which is
        # how the document itself announces what it is.
        f'<tr><td bgcolor="{_INDIGO}" style="background:{_INDIGO};'
        f'padding:24px 32px">'
        f'<div style="{_LABEL}color:{_ON_INDIGO};padding-bottom:7px">'
        f"Form NAR1 &middot; Annual Return</div>"
        f'<div style="font-family:{_FONT};font-size:20px;font-weight:600;'
        f'color:#FFFFFF;line-height:1.25;letter-spacing:-0.01em">'
        f'{_html.escape(company) or "Annual Return"}</div>'
        f"</td></tr>"

        # The sheet.
        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};'
        f'padding:32px">'
        f'<div style="font-family:{_FONT};font-size:22px;font-weight:600;'
        f'color:{_INDIGO};line-height:1.3;letter-spacing:-0.01em;'
        f'padding-bottom:14px">Please confirm these particulars</div>'
        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY}">We have prepared this year&rsquo;s annual return '
        f"for filing with the Companies Registry. It reports the company&rsquo;s "
        f"directors, secretary, registered office and share capital as they "
        f"stand on the return date.</div>"
        f"{ledger}"

        # The ask. One carrot rule, the only accent in the message.
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0"><tr>'
        f'<td width="3" bgcolor="{_CARROT}" '
        f'style="width:3px;background:{_CARROT};border-radius:2px">&nbsp;</td>'
        f'<td style="padding:2px 0 2px 18px">'
        f'<div style="{_LABEL}padding-bottom:7px">What we need from you</div>'
        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY}">Open the attached form and check every particular '
        f"against your own records. Reply to this email to confirm it is "
        f"correct, or tell us what needs changing and we will revise the form "
        f"before it is filed.</div>"
        f"</td></tr></table>"
        f"{attached}"
        f"</td></tr>"

        # Footer.
        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};'
        f'padding:18px 32px 22px;border-top:1px solid {_BORDER}">'
        f'<div style="font-family:{_FONT};font-size:12px;line-height:1.6;'
        f'color:{_T_MUTED}">'
        f'<span style="color:{_T_HEAD};font-weight:600">Get Started HK '
        f"Limited</span> &middot; Company Secretary<br>"
        f"The return is filed with the Companies Registry only after you "
        f"confirm it."
        f"</div></td></tr>"

        f"</table></td></tr></table>"
    )
    return subject, body


def _test_banner(intended_to: list[str], intended_cc: list[str]) -> str:
    """The band that says this send never left the test environment.

    Styled to match the message below it rather than bolted on as a bare
    paragraph: four people share these mailboxes across every test case, and a
    banner they skim past is a banner that fails at the one job it has.
    """
    joined = ", ".join(intended_to)
    lines = (
        f'<div style="font-family:{_FONT};font-size:13px;font-weight:600;'
        f'color:#7A2E0E;padding-bottom:4px">Test environment &mdash; not '
        f"delivered to the client</div>"
        f'<div style="font-family:{_FONT};font-size:13px;line-height:1.6;'
        f'color:{_T_BODY}">On production this would have gone to '
        f"<strong>{_html.escape(joined)}</strong>"
    )
    if intended_cc:
        lines += (f', copying <strong>{_html.escape(", ".join(intended_cc))}'
                  f"</strong>")
    lines += ".</div>"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" bgcolor="{_GROUND}" '
        f'style="background:{_GROUND}"><tr>'
        f'<td align="center" style="padding:20px 12px 0">'
        f'<table role="presentation" width="600" cellpadding="0" '
        f'cellspacing="0" border="0" style="width:600px;max-width:600px">'
        f'<tr><td style="background:#FEF0EB;border:1px solid {_CARROT};'
        f'border-radius:8px;padding:14px 18px">{lines}</td></tr>'
        f"</table></td></tr></table>"
    )
