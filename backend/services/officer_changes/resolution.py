"""The directors' written resolution an ND2A goes with (Jacqueline A3).

"For any change of director or company secretary, the company must sign an
additional written resolution for confirmation ... could the written resolution
be built from the system? In this way, the client doesn't need to receive two
separate emails."

A STANDARD Hong Kong board written resolution, built from the change list:
one resolution per cessation (accepting a resignation, or noting a death), one
per appointment, and one authorising the filing. GSHK's own sample was on the
shared drive and not available when this was written (spec C-7), which is why
attaching it to the client email is OFF by default — staff preview it first.

Signed by the directors in office before the changes (a director recorded as
deceased excepted); a company with no director in office is signed by the
incoming directors. The date lines are left blank for the signatories.
"""
from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from services.officer_changes.deadlines import _as_date

_ROLE = {"director": "a director", "company_secretary": "the company secretary"}

_BASE = ParagraphStyle("base", fontName="Times-Roman", fontSize=11, leading=15)
_TITLE = ParagraphStyle("title", parent=_BASE, fontName="Times-Bold", fontSize=13,
                        alignment=TA_CENTER, leading=17)
_CENTRE = ParagraphStyle("centre", parent=_BASE, alignment=TA_CENTER)
_HEAD = ParagraphStyle("head", parent=_BASE, fontName="Times-Bold", spaceBefore=10)
_SMALL = ParagraphStyle("small", parent=_BASE, fontSize=8.5, leading=11)


def file_name(case: dict) -> str:
    return f"Written-Resolution-{case.get('case_no') or case.get('id')}.pdf"


def _when(value) -> str:
    day = _as_date(value)
    return f"{day.day} {day:%B %Y}" if isinstance(day, date) else "the date of these resolutions"


def _name(entry: dict) -> str:
    return ((entry.get("party") or {}).get("name") or "").strip() or "the officer"


def resolutions(entries: list[dict]) -> list[tuple[str, str]]:
    """`[(heading, text)]` in the order the form reports them."""
    out = []
    for e in entries:
        role = _ROLE.get(e.get("capacity"), "an officer")
        if e.get("kind") == "cessation":
            if e.get("cessation_reason") == "D":
                out.append((f"CESSATION OF {role.split(' ', 1)[1].upper()}",
                            f"THAT it be noted that {_name(e)} ceased to be {role} of the "
                            f"Company on {_when(e.get('effective_date'))} by reason of "
                            "death."))
            else:
                out.append((f"RESIGNATION OF {role.split(' ', 1)[1].upper()}",
                            f"THAT the resignation of {_name(e)} as {role} of the Company "
                            f"with effect from {_when(e.get('effective_date'))} be and is "
                            "hereby accepted."))
        elif e.get("kind") == "appointment":
            out.append((f"APPOINTMENT OF {role.split(' ', 1)[1].upper()}",
                        f"THAT {_name(e)}, having consented to act, be and is hereby "
                        f"appointed as {role} of the Company with effect from "
                        f"{_when(e.get('effective_date'))}."))
    out.append(("FILING",
                "THAT any director or the company secretary of the Company be and is "
                "hereby authorised to sign and deliver Form ND2A to the Companies "
                "Registry and to update the statutory registers of the Company "
                "accordingly."))
    return out


def signatories(entries: list[dict], officers: list[dict]) -> list[str]:
    """The directors in office before the changes, the deceased excepted; with
    none, the incoming directors."""
    deceased = {e.get("officer_id") for e in entries
                if e.get("kind") == "cessation" and e.get("cessation_reason") == "D"}
    names = [o.get("name") for o in officers
             if o.get("role") == "director" and o.get("officer_id") not in deceased
             and o.get("name")]
    if not names:
        names = [_name(e) for e in entries
                 if e.get("kind") == "appointment" and e.get("capacity") == "director"]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def render(case: dict, entity: dict, entries: list[dict], officers: list[dict]) -> bytes:
    """The PDF."""
    company = (entity.get("company_name") or "").strip().upper() or "THE COMPANY"
    story = [Paragraph(escape(company), _TITLE),
             Paragraph("(the &ldquo;Company&rdquo;)", _CENTRE)]
    if entity.get("br_number"):
        story.append(Paragraph(f"Business Registration No. {escape(entity['br_number'])}",
                               _CENTRE))
    story += [Spacer(1, 8 * mm),
              Paragraph("WRITTEN RESOLUTIONS OF THE DIRECTORS", _TITLE),
              Paragraph("passed in writing pursuant to the Articles of Association of the "
                        "Company", _CENTRE),
              Spacer(1, 6 * mm)]
    for n, (heading, text) in enumerate(resolutions(entries), 1):
        story.append(KeepTogether([Paragraph(f"{n}. {escape(heading)}", _HEAD),
                                   Paragraph(escape(text), _BASE)]))
    story += [Spacer(1, 10 * mm), Paragraph("Signed by the directors of the Company:", _BASE)]
    for name in signatories(entries, officers):
        story.append(KeepTogether([
            Spacer(1, 14 * mm),
            Paragraph("_" * 40, _BASE),
            Paragraph(f"{escape(name)}<br/>Director", _BASE),
            Paragraph("Date: ____________________", _BASE)]))
    story += [Spacer(1, 10 * mm),
              Paragraph(f"Reference: {escape(case.get('case_no') or '')}", _SMALL)]
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=25 * mm, rightMargin=25 * mm,
                      topMargin=25 * mm, bottomMargin=20 * mm,
                      title=f"Written resolutions — {company}").build(story)
    return buffer.getvalue()
