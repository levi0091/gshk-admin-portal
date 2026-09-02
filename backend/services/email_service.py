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
import datetime as _dt
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

    `to` is an address or a sequence of them.

    NOTE FOR CALLERS: this used to carry the rule "a board of three directors is
    one message with three recipients, not three messages". THAT RULE IS
    REVERSED for client verification (spec §5): each director now needs their
    OWN approval link, and a shared link in a shared message would let any
    recipient approve in another's name. `routers/cases.send_verification`
    therefore calls this once per recipient and reports which addresses failed.
    Nothing here changed — one call is still one message — but a new caller
    should not read the old rule as advice.

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
#: The accent tint from the design system (`--carrot-10`). Used once, behind
#: the password specimen: carrot text on white fails AA at that size, and the
#: tint carries the accent without spending it on something unreadable.
_CARROT_TINT = "#FEF0EB"

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


#: GSHK's own block, transcribed from `docs/Confirmation NAR1 Notice.pdf`.
#: HARDCODED, as chosen (Levi 2026-09-01): these are the sender's details, not
#: the client's, and the sample is the approved wording. They are constants
#: rather than configuration so a deployment cannot silently change what a
#: client is told to ring.
GSHK_OFFICE_PHONE = "+ 852 2813 7600"
GSHK_RENEWAL_WHATSAPP = "+852 5541 1994"
GSHK_ADDRESS = ("Suite C, Level 7, World Trust Tower, 50 Stanley Street, "
                "Central, Hong Kong")
GSHK_SERVICES = "Corporate Advisory | Company Formation | Accounting Services"
GSHK_SENDER_TITLE = "Account Manager"

#: The three page references, verbatim from the sample.
#:
#: THEY ARE HARDCODED BECAUSE CR'S FORM IS STATIC (spec §1b). CR keeps a
#: section's page whether or not it has content, so "Page 5" is Page 5 on every
#: NAR1 ever filed. An earlier draft of this work flagged them as wrong, having
#: measured them against a renderer that DROPPED empty pages — the renderer was
#: the bug and it is fixed. If that regressed, this list would quietly misdirect
#: every client, which is why the fill tests assert a nine-page document.
NAR1_CHECK_POINTS = (
    ("Page 2", "Share capital"),
    ("Page 5", "Director's details"),
    ("Schedule 1", "Shareholder's details"),
)

#: The service charge a later amendment attracts. Sample wording: "Any
#: amendments later will incur a HK$1000 service cost."
AMENDMENT_FEE = "HK$1000"


def _first_name(full_name: str | None) -> str:
    """What to call the reader.

    Returns the WHOLE name, not a first token. The sample greets "Hi Dominique"
    because that is a Western given name; this book is mostly Hong Kong
    directors recorded surname-first, where the first token is the SURNAME and
    "Hi Chan" is not how anybody is addressed. The caller passes `given_names`
    when the record has them and the full name otherwise, so the split is made
    against the database's own field rather than guessed from a string.
    """
    return (full_name or "").strip()


def verification_email(case: dict, entity: dict,
                       attachment_name: str | None = None,
                       approval_url: str | None = None,
                       deadline=None,
                       recipient_name: str | None = None,
                       sender_name: str | None = None) -> tuple[str, str]:
    """The client-verification message: subject and HTML body.

    THE WORDING IS `docs/Confirmation NAR1 Notice.pdf`, VERBATIM (Levi
    2026-09-01), with the company, the director and the dates substituted. It
    is the letter GSHK already sends by hand, so a client who has had one
    before receives the same message from the portal — which is the point:
    an automated mail that reads differently from the one they know is an
    automated mail they treat as suspicious.

    Every interpolated value is escaped. Company names come out of the Viewpoint
    ETL, and an unescaped one lands in the client's mailbox as live markup.

    THE "NO LINK AT ALL" RULE IS REVERSED HERE (spec §5). It was a good rule and
    its reasoning still stands: a message about somebody's company filings that
    contains a link is the exact shape of the phishing it would train them to
    trust. What changed is that replying by hand was the ONLY way to answer, so
    every approval waited on a staff member reading a mailbox and a client who
    simply never replied left a case parked with nothing recorded.

    What is done about the original objection rather than around it:

      * the link opens a page that STATES nothing has been changed and asks for
        one press — it does not act on being fetched, so the mail-security
        gateway that visits every link in every message cannot approve anything;
      * that page asks for no credential, no password and no payment detail, so
        there is nothing on it worth phishing FOR;
      * the message still asks the client to reply if anything is wrong, so the
        link is the "yes" path only and the human path is unchanged;
      * `approval_url` is None when the deployment cannot build one, and the
        message then reads exactly as it did before.

    `deadline` is the date the auto-approval job will act on, read from the same
    value that job reads, so the email and the job can never state different
    dates.
    """
    company = (entity.get("company_name") or "").strip()
    case_no = (case.get("case_no") or "").strip()
    br_number = (entity.get("br_number") or "").strip()
    greeting_name = _first_name(recipient_name)
    signer = (sender_name or "").strip() or "Get Started HK Limited"

    # The sample's own subject line.
    subject = (
        f"Compliance Reminder: Registration Due - {company}"
        if company else "Compliance Reminder: Registration Due"
    )

    bullets = "".join(
        f'<tr><td style="padding:3px 0;font-family:{_FONT};font-size:15px;'
        f'line-height:1.6;color:{_T_BODY}">'
        f'<span style="font-weight:600;color:{_T_HEAD}">'
        f"{_html.escape(where)}:</span> {_html.escape(what)}</td></tr>"
        for where, what in NAR1_CHECK_POINTS
    )

    when = _deadline_text(deadline)
    # "If we do not hear from you by <date>" — omitted entirely when there is no
    # date, rather than rendered with a blank where a legal deadline should be.
    by_when = (f"If we do not hear from you by "
               f"<strong>{_html.escape(when)}</strong>, we will assume you "
               f"confirm the document and proceed with filing. "
               if when else
               "If we do not hear from you, we will assume you confirm the "
               "document and proceed with filing. ")

    attached = ""
    if attachment_name:
        attached = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" style="margin:24px 0 0"><tr>'
            f'<td style="border:1px solid {_BORDER};border-radius:6px;'
            f'padding:10px 14px;background:{_GROUND};font-family:{_FONT};'
            f'font-size:13px;color:{_T_BODY}">'
            f'<span style="{_LABEL}">Attached</span>&nbsp;&nbsp;'
            f'<span style="font-weight:600;color:{_T_HEAD}">'
            f"{_html.escape(attachment_name)}</span>"
            f"</td></tr></table>"
        )

    # The reference block. NOT in the sample letter, and kept small and last for
    # that reason: a client replying about the wrong year is the failure it
    # prevents, and it costs one line.
    reference = ""
    reference_bits = [b for b in (br_number and f"BR {br_number}",
                                  case_no and f"Ref {case_no}") if b]
    if reference_bits:
        reference = (
            f'<div style="font-family:{_FONT};font-size:12px;color:{_T_MUTED};'
            f'padding-top:16px">'
            f"{_html.escape(' · '.join(reference_bits))}</div>"
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

        # Masthead — what this is and whose company it concerns.
        f'<tr><td bgcolor="{_INDIGO}" style="background:{_INDIGO};'
        f'padding:24px 32px">'
        f'<div style="{_LABEL}color:{_ON_INDIGO};padding-bottom:7px">'
        f"Form NAR1 &middot; Annual Return</div>"
        f'<div style="font-family:{_FONT};font-size:20px;font-weight:600;'
        f'color:#FFFFFF;line-height:1.25;letter-spacing:-0.01em">'
        f'{_html.escape(company) or "Annual Return"}</div>'
        f"</td></tr>"

        # The letter.
        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};padding:32px">'

        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY};padding-bottom:16px">'
        f'Hi {_html.escape(greeting_name) or "there"},</div>'

        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY}">I enclose herewith the NAR1 for your review. '
        f"Please carefully check and confirm the following:</div>"

        f'<div style="font-family:{_FONT};font-size:15px;font-weight:600;'
        f'color:{_T_HEAD};padding:20px 0 6px">'
        f"1. NAR1 Form - Signature not required</div>"

        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:0 0 6px">{bullets}</table>'

        # The director's duty, the deadline and the amendment charge — the one
        # paragraph in this message with legal weight, so it gets the single
        # carrot rule the design spends its accent on.
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" style="margin:22px 0 0"><tr>'
        f'<td width="3" bgcolor="{_CARROT}" '
        f'style="width:3px;background:{_CARROT};border-radius:2px">&nbsp;</td>'
        f'<td style="padding:2px 0 2px 18px">'
        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY}">Please note that the director has the duty to '
        f"ensure <strong>ALL</strong> information on NAR1 is correct before "
        f"registration. {by_when}Any amendments later will incur a "
        f"{_html.escape(AMENDMENT_FEE)} service cost.</div>"
        f"</td></tr></table>"

        f"{_approval_button(approval_url, None)}"
        f'<div style="font-family:{_FONT};font-size:13px;line-height:1.6;'
        f'color:{_T_MUTED};padding-top:14px">'
        f"{_confirm_instruction(approval_url)}</div>"

        f"{attached}"

        # Signature block, from the sample.
        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY};padding-top:26px">Best regards,</div>'
        f'<div style="font-family:{_FONT};font-size:15px;font-weight:600;'
        f'color:{_T_HEAD};padding-top:14px">{_html.escape(signer)}</div>'
        f'<div style="font-family:{_FONT};font-size:14px;color:{_T_BODY}">'
        f"{_html.escape(GSHK_SENDER_TITLE)}</div>"
        f"{reference}"
        f"</td></tr>"

        # Footer — GSHK's own block, verbatim.
        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};'
        f'padding:18px 32px 22px;border-top:1px solid {_BORDER}">'
        f'<div style="font-family:{_FONT};font-size:13px;font-weight:600;'
        f'color:{_T_HEAD};padding-bottom:4px">GET STARTED HK LIMITED</div>'
        f'<div style="font-family:{_FONT};font-size:12px;line-height:1.6;'
        f'color:{_T_MUTED}">'
        f"Office: {_html.escape(GSHK_OFFICE_PHONE)} | Renewal whatsapp: "
        f"{_html.escape(GSHK_RENEWAL_WHATSAPP)}<br>"
        f"{_html.escape(GSHK_ADDRESS)}<br>"
        f"{_html.escape(GSHK_SERVICES)}"
        f"</div></td></tr>"

        f"</table></td></tr></table>"
    )
    return subject, body


def _confirm_instruction(approval_url: str | None) -> str:
    """What the reader is asked to do — which differs by whether a link exists.

    Kept as one sentence per case rather than a link appended to a fixed
    sentence: "Reply to confirm" followed by a Confirm button asks for the same
    thing twice, and a reader doing both produces two answers for one return.
    """
    if approval_url:
        return ("If it is correct, press <strong>Confirm</strong> below. If "
                "anything needs changing, reply to this email and tell us what "
                "is wrong &mdash; we will revise the form before it is filed.")
    return ("Reply to this email to confirm it is correct, or tell us what "
            "needs changing and we will revise the form before it is filed.")


def _approval_button(approval_url: str | None, deadline) -> str:
    """The one-press confirmation (spec §5), or nothing at all.

    A BULLETPROOF button: a bordered table cell with the anchor filling it, not
    a styled `<a>`. Outlook renders mail through Word, which drops padding on
    inline anchors and leaves a bare blue link where the call to action should
    be — the same reason this whole message is tables and inline styles.

    The URL is escaped like every other interpolated value. It is ours, not the
    client's, but the escaping rule in this module has no exceptions: the one
    place a rule is relaxed is where the next injection lands.
    """
    if not approval_url:
        return ""
    note = ""
    when = _deadline_text(deadline)
    if when:
        note = (f'<div style="font-family:{_FONT};font-size:13px;'
                f'line-height:1.6;color:{_T_MUTED};padding-top:12px">'
                f"If we do not hear from you by {_html.escape(when)}, we will "
                f"proceed with filing this return as prepared.</div>")
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:26px 0 0"><tr>'
        f'<td bgcolor="{_CARROT}" style="background:{_CARROT};'
        f'border-radius:6px" align="center">'
        f'<a href="{_html.escape(approval_url, quote=True)}" '
        f'style="display:inline-block;padding:13px 26px;font-family:{_FONT};'
        f'font-size:15px;font-weight:600;color:#FFFFFF;text-decoration:none">'
        f"Confirm these particulars are correct</a>"
        f"</td></tr></table>"
        f"{note}"
    )


def _deadline_text(deadline) -> str:
    """The expiry as a client would read it, in Hong Kong time.

    Accepts a datetime or an ISO string, because the caller gets one from the
    token issuer and the other from a stored row. An unparseable value yields
    "" and the sentence is simply omitted — a wrong date on a legal deadline is
    worse than no date.
    """
    if not deadline:
        return ""
    moment = deadline
    if not hasattr(moment, "strftime"):
        try:
            moment = _dt.datetime.fromisoformat(
                str(deadline).replace("Z", "+00:00"))
        except ValueError:
            return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    hkt = moment.astimezone(_dt.timezone(_dt.timedelta(hours=8)))
    return hkt.strftime("%d %B %Y")


#: PROD and DEV, and nothing else. Derived from APP_ENV rather than hardcoded
#: at the call site: a welcome email that sent a DEV colleague to the production
#: portal would have them sign in somewhere their account does not exist, and
#: the reverse would put a production user on the test database.
_PORTAL_URLS = {
    True: "https://admin.g-flowdesk.com",
    False: "https://admin-dev.g-flowdesk.com",
}

#: Monospace, for the password specimen only. The reader is going to read this
#: character by character, and a proportional face makes l/1/I and O/0
#: ambiguous — which is a usability property of a credential, not a style
#: choice. Every face named is present by default on Windows, macOS or a mail
#: client's own fallback; there is no webfont to fail to load.
_MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,Courier,monospace"


def portal_url() -> str:
    """Where a new user signs in.

    `ADMIN_PORTAL_URL` overrides, for the Cloudflare Pages preview deployments
    that have their own hostname and are neither of the two below.
    """
    override = (os.environ.get("ADMIN_PORTAL_URL") or "").strip()
    if override.lower().startswith(("http://", "https://")):
        return override.rstrip("/")
    return _PORTAL_URLS[app_env.is_production()]


def welcome_email(display_name: str, role_name: str | None,
                  password: str) -> tuple[str, str]:
    """The message a newly created user receives: subject and HTML body.

    THE PASSWORD IS THE POINT OF THIS EMAIL, so it is set as a specimen — a
    bordered, letter-spaced, monospaced block with its own label — rather than
    dropped into a sentence. Everything around it stays quiet. The reader's
    whole job is to carry those characters to a login box, and a credential
    they have to hunt for in a paragraph is one they will mistype.

    It exists in exactly two places: this message, and Supabase Auth's hash. It
    is never returned by the API and never written to a log or an audit row —
    see `routers/users.create_user`.

    Same constraints as the client-facing mail, and for the same reasons:
    table-based with inline styles, because Outlook renders through Word and
    has no flexbox, no grid and no reliable `<style>` block; and a real
    fallback stack, because Outfit does not load in most mail clients, so the
    fallback IS the typography.
    """
    name = (display_name or "").strip()
    url = portal_url()

    subject = "Your G-FlowDesk account is ready"

    role_line = ""
    if role_name:
        role_line = (
            f'<div style="{_LABEL}padding:22px 0 3px">Your role</div>'
            f'<div style="font-family:{_FONT};font-size:15px;font-weight:600;'
            f'color:{_T_HEAD}">{_html.escape(role_name)}</div>'
            f'<div style="font-family:{_FONT};font-size:13px;line-height:1.6;'
            f'color:{_T_MUTED};padding-top:3px">This decides which parts of the '
            f"portal you can open. Ask an administrator if you need more.</div>"
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

        # Masthead — the same one the client mail wears, so the two read as one
        # system rather than as two products.
        f'<tr><td bgcolor="{_INDIGO}" style="background:{_INDIGO};'
        f'padding:24px 32px">'
        f'<div style="{_LABEL}color:{_ON_INDIGO};padding-bottom:7px">'
        f"G-FlowDesk &middot; Admin Portal</div>"
        f'<div style="font-family:{_FONT};font-size:20px;font-weight:600;'
        f'color:#FFFFFF;line-height:1.25;letter-spacing:-0.01em">'
        f"Your account is ready</div>"
        f"</td></tr>"

        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};padding:32px">'

        f'<div style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_T_BODY}">'
        f'Hi {_html.escape(name) or "there"}, an administrator has created your '
        f"G-FlowDesk account. Sign in with the password below.</div>"

        # THE SPECIMEN. The one place this message spends any boldness.
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" style="border-collapse:separate;'
        f'margin:24px 0 0"><tr>'
        f'<td bgcolor="{_CARROT_TINT}" style="background:{_CARROT_TINT};'
        f'border:1px solid {_CARROT};border-radius:8px;padding:18px 22px">'
        f'<div style="{_LABEL}padding-bottom:8px">Temporary password</div>'
        f'<div style="font-family:{_MONO};font-size:22px;font-weight:700;'
        f'letter-spacing:0.06em;color:{_T_HEAD};word-break:break-all;'
        f'line-height:1.35">{_html.escape(password)}</div>'
        f"</td></tr></table>"

        f'<div style="font-family:{_FONT};font-size:13px;line-height:1.6;'
        f'color:{_T_MUTED};padding-top:10px">'
        f"Use it for your first sign-in only. You will be asked to choose your "
        f"own password straight away, and nothing else in the portal opens "
        f"until you do.</div>"

        # The action.
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:24px 0 0"><tr>'
        f'<td bgcolor="{_INDIGO}" style="background:{_INDIGO};'
        f'border-radius:6px" align="center">'
        f'<a href="{_html.escape(url, quote=True)}" '
        f'style="display:inline-block;padding:13px 26px;font-family:{_FONT};'
        f'font-size:15px;font-weight:600;color:#FFFFFF;text-decoration:none">'
        f"Sign in to G-FlowDesk</a>"
        f"</td></tr></table>"

        # The URL in full, under the button. A reader on a client that strips
        # anchors, or one who does not press links in email on principle, still
        # has something they can type.
        f'<div style="font-family:{_FONT};font-size:12px;line-height:1.6;'
        f'color:{_T_MUTED};padding-top:10px;word-break:break-all">'
        f"{_html.escape(url)}</div>"

        f"{role_line}"
        f"</td></tr>"

        f'<tr><td bgcolor="{_SHEET}" style="background:{_SHEET};'
        f'padding:18px 32px 22px;border-top:1px solid {_BORDER}">'
        f'<div style="font-family:{_FONT};font-size:12px;line-height:1.6;'
        f'color:{_T_MUTED}">'
        f'<span style="color:{_T_HEAD};font-weight:600">G-FlowDesk</span> '
        f"&middot; Get Started HK Limited<br>"
        f"If you were not expecting this, tell your administrator and do not "
        f"sign in."
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
