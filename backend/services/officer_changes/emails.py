"""The client-verification email for an officer change (ND2A / ND2B).

GSHK's own templates, VERBATIM (Levi 2026-11-06: `ND2A Notification` and
`ND2B Notification`). This replaces the earlier draft in the NAR1 letter's
structure, whose body listed the changes, carried a protected-information
paragraph, a respond-by date and, for an ND2B, "we will proceed with filing".
The template has a place for none of those, and the wording is GSHK's to set:
"Dear Client," / "Your Form ND2A is now available." / what to check / the
approval declaration the Confirm button makes / what happens after / where an
error goes / "Kind regards, Get Started HK Limited" / the button.

What carries over from the NAR1 letter, because the templates do not contradict
it and other features depend on it: the masthead, the GSHK footer, the revision
notice and `[Rev. N]` subject (`email_service.revision_notice` / `with_revision`,
so the three forms word a resend identically), the list of attached files, the
note on an incoming director's e-Registry consent, and the no-approval-link
fallback.

THE FALLBACK. With no approval link there is no button, so "click the Confirm
button" and the declaration made by clicking it would describe something that is
not there. That path asks for a reply through `email_service._confirm_instruction`
(the same sentence the NAR1 letter uses), drops the declaration and the promise
of a receipt (a receipt is only sent when a link is pressed), and withholds the
"replies are not monitored" line, which would contradict the request.

What it deliberately does NOT carry: any identity number or home address in the
body (the ATTACHED draft is CR's full form, PI sheets included), and any claim
that silence is consent. Nothing is approved on silence.

Outlook renders mail through Word: tables and inline styles only, every
interpolated value escaped.
"""
from __future__ import annotations

import html as _html

from services import email_service as es
from services.officer_changes.deadlines import _as_date

_FORM = {
    "Nd2a": ("ND2A", "Appointment and cessation of company officers",
             "ND2A Review & Confirmation"),
    "Nd2b": ("ND2B", "Change of particulars of company officers",
             "ND2B Review & Confirmation"),
}
_CAPACITY = {"director": "Director", "company_secretary": "Company Secretary",
             "alternate_director": "Alternate Director"}
#: How each ND2B item reads in a letter that may be forwarded: names are shown,
#: an email address is shown (it is a contact, not an identifier), and nothing
#: that would let a stranger find a home or impersonate an identity document.
_SHOWS_VALUE = {"name_zh", "name_en", "alias", "name", "email"}


#: Jacqueline A1: "most of our clients ... prefer to let us fill in the most
#: recent date". A change sent undated says so in these words.
TO_BE_CONFIRMED = "with effect from a date to be confirmed when we file this notice"


def _day(value) -> str:
    when = _as_date(value)
    return f"{when:%d %B %Y}" if when else "a date to be confirmed"


def _on(value) -> str:
    """" on 28 September 2026" — or ", with effect from a date to be confirmed…"."""
    return f" on {_day(value)}" if _as_date(value) else f", {TO_BE_CONFIRMED}"


def _name(entry: dict) -> str:
    return ((entry.get("party") or {}).get("name") or "").strip() or "An officer"


def changes_summary(entries: list[dict]) -> list[str]:
    """One line per change. Never a full identity number or a home address."""
    lines = []
    for entry in entries:
        capacity = _CAPACITY.get(entry.get("capacity"), "officer")
        kind = entry.get("kind")
        if kind == "cessation":
            why = " (deceased)" if entry.get("cessation_reason") == "D" else ""
            lines.append(f"{_name(entry)} ceases to act as {capacity}"
                         f"{_on(entry.get('effective_date'))}{why}.")
        elif kind == "appointment":
            lines.append(f"{_name(entry)} is appointed {capacity}"
                         f"{_on(entry.get('effective_date'))}.")
        elif kind == "change":
            for item in entry.get("items") or []:
                if item.get("omitted"):
                    continue
                label = item.get("label") or item.get("key")
                if item.get("key") in _SHOWS_VALUE:
                    what = (f"{label} changed from {item.get('old_text') or '—'} "
                            f"to {item.get('new_text') or '—'}")
                else:
                    what = f"{label} changed"
                when = (f"effective {_day(item.get('effective_date'))}"
                        if _as_date(item.get("effective_date")) else TO_BE_CONFIRMED)
                lines.append(f"{_name(entry)} ({capacity}): {what}, {when}.")
    return lines


def _para(text_html: str, top: int = 14) -> str:
    return (f'<div style="font-family:{es._FONT};font-size:15px;line-height:1.65;'
            f'color:{es._T_BODY};padding-top:{top}px">{text_html}</div>')


def _button(approval_url: str | None, label: str, *, colour: str | None = None) -> str:
    if not approval_url:
        return ""
    colour = colour or es._CARROT
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:26px 0 4px"><tr><td align="center">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td bgcolor="{colour}" style="background:{colour};'
        f'border-radius:6px" align="center">'
        f'<a href="{_html.escape(approval_url, quote=True)}" '
        f'style="display:inline-block;padding:14px 40px;font-family:{es._FONT};'
        f'font-size:17px;font-weight:600;color:#FFFFFF;text-decoration:none">'
        f"{_html.escape(label)}</a></td></tr></table></td></tr></table>"
    )


def _consent_paragraph(consent: dict | None) -> str:
    """For the incoming director's own letter (Jacqueline A5)."""
    mode = (consent or {}).get("mode")
    if mode == "esign":
        return _para("<strong>No signature is needed from you.</strong> We will apply your "
                     "consent to act as a director through the e-Registry account we set "
                     "up with you.", top=14)
    return ""


def _attachments_line(names) -> str:
    names = [n for n in names or [] if n]
    if not names:
        return ""
    return (f'<div style="font-family:{es._FONT};font-size:13px;color:{es._T_BODY};'
            f'padding-top:18px"><span style="{es._LABEL}color:{es._T_MUTED}">Attached:'
            f"</span> {' &middot; '.join(_html.escape(n) for n in names)}</div>")


#: What each form's letter says, word for word from GSHK's templates. The two
#: differ in small places that are GSHK's to settle, not ours: ND2B's
#: declaration reads "the information in document" (no "the"), its first
#: sentence says "If the information" where ND2A says "If all information", and
#: the two error paragraphs open "When you identify" / "If you identify" and
#: close "If the form" / "When the form". Each is copied exactly rather than
#: normalised, so a re-read against the PDF finds no drift.
#:
#: `bullets` is `(line, sub-lines)`: ND2B's Page 2 bullet carries three
#: indented "(if applicable)" lines beneath it.
_WORDING = {
    "Nd2a": {
        "bullets": [("Director’s name", []), ("Director's Details", [])],
        "approve_lead": "If all information is correct, please ",
        "declaration": (
            "“I confirm that I am authorised to approve this document on behalf of "
            "the company. I have reviewed the document and confirm that the information "
            "in it is correct and complete to the best of my knowledge. I approve this "
            "version and authorise Get Started HK Limited to submit it to the Companies "
            "Registry on behalf of the company.”"),
        "error_lead": "When you identify any error, do not approve the document. Contact ",
        "error_tail": "If the form has already been submitted, changes may also require "
                      "a separate correction or further filing.",
    },
    "Nd2b": {
        "bullets": [
            ("Page 2:", ["Correspondence Address (if applicable)",
                         "Partial Number of Hong Kong Identity Card (if applicable)",
                         "Partial Number of Passport (if applicable)"]),
            ("PI-ND2B: Director’s Residential Address and/or Passport Details", []),
        ],
        "approve_lead": "If the information is correct, please ",
        "declaration": (
            "“I confirm that I am authorised to approve this document on behalf of "
            "the company. I have reviewed and confirmed that the information in document "
            "is correct and complete to the best of my knowledge. I approve this version "
            "and authorise Get Started HK Limited to submit it to the Companies Registry "
            "on behalf of the company.”"),
        "error_lead": "If you identify any error, do not approve the document. Contact ",
        "error_tail": "When the form has already been submitted, changes may also require "
                      "a separate correction or further filing.",
    },
}


def _heading(text: str) -> str:
    return (f'<div style="font-family:{es._FONT};font-size:15px;font-weight:600;'
            f'color:{es._T_HEAD};padding-top:26px">{_html.escape(text)}</div>')


def _bullets(items) -> str:
    """The "particular attention" list, as table rows Outlook can be trusted with.

    A bullet's sub-lines sit in the same cell under it, unmarked, as the ND2B
    template sets Page 2's three "(if applicable)" lines.
    """
    rows = []
    for line, subs in items:
        text = _html.escape(line) + "".join(
            f"<br>{_html.escape(sub)}" for sub in subs)
        rows.append(
            f'<tr><td width="22" valign="top" style="width:22px;padding:4px 0 0;'
            f'font-family:{es._FONT};font-size:15px;line-height:1.6;'
            f'color:{es._T_BODY}">&bull;</td>'
            f'<td style="padding:4px 0;font-family:{es._FONT};font-size:15px;'
            f'line-height:1.6;color:{es._T_BODY}">{text}</td></tr>')
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:6px 0 0 18px">{"".join(rows)}</table>')


def _quote(text: str) -> str:
    """The declaration, indented as the template sets it."""
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="margin:12px 0 0"><tr><td width="28" '
            'style="width:28px">&nbsp;</td>'
            f'<td style="font-family:{es._FONT};font-size:15px;line-height:1.65;'
            f'color:{es._T_BODY}">{_html.escape(text)}</td></tr></table>')


def _mailbox() -> str:
    mailbox = _html.escape(es.RENEWAL_MAILBOX)
    return (f'<a href="mailto:{mailbox}" style="color:{es._INDIGO};font-weight:600;'
            f'text-decoration:underline">{mailbox}</a>')


def officer_change_email(case: dict, entity: dict, entries: list[dict], *,
                         approval_url: str | None, respond_by=None,
                         revision=None, attachments=(),
                         consent: dict | None = None) -> tuple[str, str]:
    """`(subject, html)`.

    `entries` and `respond_by` are accepted and no longer printed: the template
    names what to check by form rather than listing each change, and has no
    deadline sentence. They stay in the signature so the callers, which still
    hold both, need no change.

    `attachments` names every file attached, listed under "Attached:".
    `consent` is set only on an incoming director's own letter, and only when
    GSHK PIN-signs their consent from their stored e-Registry account:
    `{"mode": "esign", "name"}`. There is no in-portal consent (Levi
    2026-10-05: CR's consent signature is the consent).

    `revision` is which verification email this is for the case (Levi
    2026-10-02, migration 051). From the second on it reads exactly as NAR1's
    does — "[Rev. N]" in the subject, "Rev. N" in the masthead and reference
    line, and the shared notice above "Dear Client" that the earlier email's
    Confirm button no longer works — through `email_service`'s own helpers, so
    the three forms cannot word it differently. The first is unchanged.
    """
    code, title, subject_title = _FORM.get(case.get("form_code"), _FORM["Nd2a"])
    wording = _WORDING["Nd2b" if code == "ND2B" else "Nd2a"]
    company = (entity.get("company_name") or "").strip()
    rev = es.revision_label(revision)
    subject = es.with_revision(
        f"[Action Required] {subject_title} - {company}" if company
        else f"[Action Required] {subject_title}",
        revision)
    reference = " · ".join(b for b in (
        entity.get("br_number") and f"BR {entity['br_number']}",
        case.get("case_no") and f"Ref {case['case_no']}",
        rev) if b)

    if approval_url:
        # The template's paragraph, with the Confirm button named by its label.
        approval = (
            _para(f"{_html.escape(wording['approve_lead'])}<strong>click the "
                  f"“Confirm {code}” button</strong>. By clicking this, you make "
                  "the following declaration:", top=10)
            + _quote(wording["declaration"])
            + _para("We can proceed with submission only after receiving your approval. "
                    "Our system will record your approval and send you a Submission "
                    "Authorisation Receipt.", top=18))
    else:
        # No button: nothing to click, no declaration to make by clicking, and no
        # receipt (it is sent when a link is pressed). See the module docstring.
        approval = (
            _para(es._confirm_instruction(None), top=10)
            + _para("We can proceed with submission only after receiving your approval.",
                    top=14))

    body = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" bgcolor="{es._GROUND}" style="background:{es._GROUND};margin:0;'
        f'padding:0"><tr><td align="center" style="padding:28px 12px">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="width:600px;max-width:600px;border-collapse:separate;'
        f'border-radius:10px;overflow:hidden;border:1px solid {es._BORDER}">'
        # Masthead: the form, then whose company — as CR's own form heads it.
        f'<tr><td bgcolor="{es._INDIGO}" style="background:{es._INDIGO};'
        f'padding:24px 32px"><div style="{es._LABEL}color:{es._ON_INDIGO};'
        f'padding-bottom:7px">Form {code} &middot; {_html.escape(title)}'
        f'{f" &middot; {_html.escape(rev)}" if rev else ""}</div>'
        f'<div style="font-family:{es._FONT};font-size:20px;font-weight:600;'
        f'color:#FFFFFF;line-height:1.25">{_html.escape(company) or code}</div>'
        f"</td></tr>"
        f'<tr><td bgcolor="{es._SHEET}" style="background:{es._SHEET};padding:32px">'
        # Empty on the first email; on a revision, the first thing read.
        + es.revision_notice(revision)
        + _para("Dear Client,", top=0)
        + _para(f"Your Form {code} is now available.")
        + _para("Please review the attached Form carefully, with particular attention:")
        + _bullets(wording["bullets"])
        + _consent_paragraph(consent)
        + _heading("Approval and authorisation")
        + approval
        + _heading("Errors or changes")
        + _para(f"{_html.escape(wording['error_lead'])}{_mailbox()} immediately. Any "
                f"changes you request after approval will be subject to a "
                f"{_html.escape(es.AMENDMENT_FEE)} service fee. "
                f"{_html.escape(wording['error_tail'])}", top=10)
        + es._unmonitored_notice(approval_url)
        + _para("Kind regards,", top=26)
        + f'<div style="font-family:{es._FONT};font-size:15px;font-weight:600;'
          f'color:{es._T_HEAD};padding-top:4px">Get Started HK Limited</div>'
        + _button(approval_url, f"Confirm {code}")
        + _attachments_line(attachments)
        + (f'<div style="font-family:{es._FONT};font-size:12px;color:{es._T_MUTED};'
           f'padding-top:16px">{_html.escape(reference)}</div>' if reference else "")
        + "</td></tr>"
        f'<tr><td bgcolor="{es._SHEET}" style="background:{es._SHEET};'
        f'padding:18px 32px 22px;border-top:1px solid {es._BORDER}">'
        f'<div style="font-family:{es._FONT};font-size:13px;font-weight:600;'
        f'color:{es._T_HEAD};padding-bottom:4px">GET STARTED HK LIMITED</div>'
        f'<div style="font-family:{es._FONT};font-size:12px;line-height:1.6;'
        f'color:{es._T_MUTED}">Office: {_html.escape(es.GSHK_OFFICE_PHONE)} | '
        f"Renewal whatsapp: {_html.escape(es.GSHK_RENEWAL_WHATSAPP)}<br>"
        f"{_html.escape(es.GSHK_ADDRESS)}<br>{_html.escape(es.GSHK_SERVICES)}"
        f"</div></td></tr></table></td></tr></table>"
    )
    return subject, body
