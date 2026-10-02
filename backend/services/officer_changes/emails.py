"""The client-verification email for an officer change (ND2A / ND2B).

A DRAFT in the NAR1 letter's structure (spec B-14, PRD Q14 still open): the
same masthead, the same "Dear Client" / "Kind regards, Get Started HK Limited",
the same unmonitored-reply notice and `renewal@getstarted.hk` for changes, the
same bulletproof Confirm button. It reuses `email_service`'s tokens and helpers
rather than copying them, so the two letters cannot drift apart in look or in
the rules about where a client writes.

What it deliberately does NOT carry:
  * any full identity number or any home address — the summary says an address
    or an ID "changed", and the attached public pages carry partial numbers
    only (the PI sheets are not attached);
  * the NAR1 line "if we do not hear from you ... deemed confirmed". There is
    NO auto-approval for an officer change (spec §5): silence is not consent
    to tell CR who runs a company;
  * NAR1's HK$1,000 amendment fee, which is a NAR1 rule.

Outlook renders mail through Word: tables and inline styles only, every
interpolated value escaped.
"""
from __future__ import annotations

import html as _html
from datetime import date

from services import email_service as es
from services.officer_changes.deadlines import _as_date

_FORM = {
    "Nd2a": ("ND2A", "Appointment and cessation of company officers",
             "ND2A Review & Confirmation"),
    "Nd2b": ("ND2B", "Change of particulars of company officers",
             "ND2B Review & Confirmation"),
}
_CAPACITY = {"director": "Director", "company_secretary": "Company Secretary"}
#: How each ND2B item reads in a letter that may be forwarded: names are shown,
#: an email address is shown (it is a contact, not an identifier), and nothing
#: that would let a stranger find a home or impersonate an identity document.
_SHOWS_VALUE = {"name_zh", "name_en", "alias", "name", "email"}


def _day(value) -> str:
    when = _as_date(value)
    return f"{when:%d %B %Y}" if when else "a date to be confirmed"


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
            lines.append(f"{_name(entry)} ceases to act as {capacity} on "
                         f"{_day(entry.get('effective_date'))}{why}.")
        elif kind == "appointment":
            lines.append(f"{_name(entry)} is appointed {capacity} on "
                         f"{_day(entry.get('effective_date'))}.")
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
                lines.append(f"{_name(entry)} ({capacity}): {what}, effective "
                             f"{_day(item.get('effective_date'))}.")
    return lines


def _para(text_html: str, top: int = 14) -> str:
    return (f'<div style="font-family:{es._FONT};font-size:15px;line-height:1.65;'
            f'color:{es._T_BODY};padding-top:{top}px">{text_html}</div>')


def _button(approval_url: str | None, label: str) -> str:
    if not approval_url:
        return ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin:26px 0 4px"><tr><td align="center">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td bgcolor="{es._CARROT}" style="background:{es._CARROT};'
        f'border-radius:6px" align="center">'
        f'<a href="{_html.escape(approval_url, quote=True)}" '
        f'style="display:inline-block;padding:14px 40px;font-family:{es._FONT};'
        f'font-size:17px;font-weight:600;color:#FFFFFF;text-decoration:none">'
        f"{_html.escape(label)}</a></td></tr></table></td></tr></table>"
    )


def officer_change_email(case: dict, entity: dict, entries: list[dict], *,
                         approval_url: str | None, respond_by,
                         revision=None) -> tuple[str, str]:
    """`(subject, html)`.

    `revision` is which verification email this is for the case (Levi
    2026-10-02, migration 051). From the second on it reads exactly as NAR1's
    does — "[Rev. N]" in the subject, "Rev. N" in the masthead and reference
    line, and the shared notice above "Dear Client" that the earlier email's
    Confirm button no longer works — through `email_service`'s own helpers, so
    the three forms cannot word it differently. The first is unchanged.
    """
    code, title, subject_title = _FORM.get(case.get("form_code"), _FORM["Nd2a"])
    company = (entity.get("company_name") or "").strip()
    rev = es.revision_label(revision)
    subject = es.with_revision(
        f"[Action Required] {subject_title} - {company}" if company
        else f"[Action Required] {subject_title}",
        revision)
    when = _as_date(respond_by) if not isinstance(respond_by, date) else respond_by

    bullets = "".join(
        f'<tr><td width="14" valign="top" style="width:14px;padding:4px 0 0;'
        f'font-family:{es._FONT};font-size:15px;line-height:1.6;'
        f'color:{es._T_MUTED}">&bull;</td>'
        f'<td style="padding:4px 0;font-family:{es._FONT};font-size:15px;'
        f'line-height:1.6;color:{es._T_BODY}">{_html.escape(line)}</td></tr>'
        for line in changes_summary(entries)
    )
    by_when = (f"Please let us know by <strong>{when:%d %B %Y}</strong>. "
               if when else "Please let us know as soon as possible. ")
    reference = " · ".join(b for b in (
        entity.get("br_number") and f"BR {entity['br_number']}",
        case.get("case_no") and f"Ref {case['case_no']}",
        rev) if b)

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
        + _para(f"A draft Form {code} for {_html.escape(company) or 'your company'} "
                "is ready for your review. It reports the following changes to "
                "the company's officers:")
        + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
          f'style="margin:10px 0 0">{bullets}</table>'
        + _para("Please review the attached draft carefully. Personal identity "
                "numbers and residential addresses are not shown in this email "
                "or in the draft; they are filed with the Companies Registry on a "
                "separate sheet that is not open to public inspection.", top=20)
        + _para(es._confirm_instruction(approval_url), top=14)
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
          f'border="0" style="margin:20px 0 0"><tr><td width="3" '
          f'bgcolor="{es._CARROT}" style="width:3px;background:{es._CARROT};'
          f'border-radius:2px">&nbsp;</td><td style="padding:2px 0 2px 18px">'
        + _para(f"{by_when}The Companies Registry must receive this form within "
                "15 days of the change.", top=0)
        + _para(es._change_instruction(approval_url), top=12)
        + "</td></tr></table>"
        + es._unmonitored_notice(approval_url)
        + _para("Kind regards,", top=26)
        + f'<div style="font-family:{es._FONT};font-size:15px;font-weight:600;'
          f'color:{es._T_HEAD};padding-top:4px">Get Started HK Limited</div>'
        + _button(approval_url, f"Confirm {code}")
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
