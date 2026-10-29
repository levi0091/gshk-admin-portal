"""The confirmation receipt — mailed after a client's own Confirm & File.

Levi 2026-10-17: "after a director or secretary or any client click on the
confirm file & sign button in the weblink ... they should get an email
confirmation that they have signed the document on what date and time and
attach the document(s) in that email also ... the same for ND2A, ND2B or NAR1
client verification step. cc renewal@getstarted.hk."

WHEN. Once per approval, queued by `routers/public_approval._record` only after
`nar1_approvals.claim` succeeded — so a GET, a replayed press, a stale or
expired link and the director who lost the race never send one. Not on a
staff-relayed answer, the 14-day auto-approval or an ND2B waiver: nobody
pressed anything there.

WHAT IT CARRIES. The documents the client confirmed, named as the verification
email named them: the FROZEN `verification_xml` the case stored at the send
(NAR1, ND2A, ND2B), rendered exactly as the send renders it, and for an ND2A
the written resolution. Not the supporting uploads — the client confirmed the
form, not their own passport scan. A document that cannot be rendered is left
off and named in the audit row; the receipt still goes, and lists only what it
carries.

WHAT IT NAMES (Levi 2026-10-29). Every document the client confirmed, by title
in the stamp's Documents row, from `confirmed_documents` — the same list the
Confirm & File page shows — whether or not its attachment rendered. The
Attached box still lists only files actually attached.

HOW. A FastAPI background task, after the confirmation page has been returned:
the director never waits on a PDF render or on Resend. It NEVER raises —
everything is caught and printed to stderr, because by the time it runs the
approval is recorded and there is nobody left to show an error to.

THE TRAIL. One `EMAIL_SENT` row, the code CLAUDE.md mandates for every workflow
email, tagged `metadata.template = "approval_receipt"`. The delivery check
(`GET …/verification/delivery`) reads the newest EMAIL_SENT row on a case and
skips tagged ones, so a receipt can never be reported as the verification send.
"""
from __future__ import annotations

import asyncio
import sys

from services import audit_events as ev
from services import audit_subject, email_service, nar1_cases
from services.audit_service import log_event
from services.nar1_form import fill as nar1_form_fill
from services.officer_change_form import render as render_officer_form
from services.officer_changes import cases as officer_cases
from services.officer_changes import resolution

TEMPLATE = "approval_receipt"
ACTOR = "G-FlowDesk (automatic)"

_PREFIX = {"Nar1": "NAR1", "Nd2a": "ND2A", "Nd2b": "ND2B"}


def _revision(case: dict, approval: dict) -> int:
    """The revision the director confirmed: their link's, else the case's."""
    for value in (approval.get("revision"), case.get("verification_revision")):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return 1


def _form_file_name(case: dict, revision: int) -> str:
    """As the verification email named it: `NAR1-<case no>[-RevN].pdf`."""
    prefix = _PREFIX.get(case.get("form_code") or "Nar1", "NAR1")
    return (f"{prefix}-{case.get('case_no') or case['id']}"
            f"{f'-Rev{revision}' if revision >= 2 else ''}.pdf")


RESOLUTION_TITLE = "Written resolution of the directors"


def confirmed_documents(case: dict, approval: dict) -> list[dict]:
    """What the client is confirming: `[{"title", "file_name"}]`, one per document.

    THE ONE LIST behind the Confirm & File page ("You are confirming") and the
    receipt's Documents row (nd2-change-requests PRD section 6, Levi 2026-10-29),
    so the page, the receipt and the verification email's attachments cannot
    name three different sets. PURE: no I/O, so a page render never waits on a
    PDF, and the receipt can name a document whose attachment failed to render.

    `approval` is the link's own row, because the revision is the link's before
    it is the case's (`_revision`): a director who confirmed Rev. 1 is not told
    they confirmed Rev. 2. File names come from `_form_file_name` and
    `resolution.file_name`, which MIRROR the send's inline names rather than
    being the code that builds them — `test_approval_receipt.py` pins the three
    forms against the send's formulas. An ND2A is always sent with its written
    resolution (Levi 2026-10-05), which carries no revision of its own.
    """
    form_code = case.get("form_code") or "Nar1"
    revision = _revision(case, approval or {})
    year = case.get("ar_period_year") if form_code == "Nar1" else None
    docs = [{"title": email_service.confirmed_form_title(form_code, year, revision),
             "file_name": _form_file_name(case, revision)}]
    if form_code == "Nd2a":
        docs.append({"title": RESOLUTION_TITLE, "file_name": resolution.file_name(case)})
    return docs


async def _render_form(case: dict, entity: dict, xml: str) -> bytes:
    filing = nar1_cases.current_filing(case["id"])
    submitted_on = nar1_cases.filed_on(filing, case)
    form_code = case.get("form_code") or "Nar1"
    if form_code == "Nar1":
        return await asyncio.to_thread(
            nar1_form_fill.render, xml,
            company_type=nar1_form_fill.company_type_from_profile(entity.get("company_type")),
            submitted_on=submitted_on,
            incorporated_on=entity.get("incorporation_date"))
    name = "  ".join(p for p in (entity.get("company_name"), entity.get("company_name_zh")) if p)
    return await asyncio.to_thread(
        render_officer_form, form_code, xml, company_name=name, public_only=False,
        submitted_on=submitted_on)


async def documents(case: dict, entity: dict, approval: dict) -> tuple[list, list]:
    """(files, failures): `[(name, bytes)]` attached, `[{file, reason}]` not."""
    files: list[tuple[str, bytes]] = []
    failures: list[dict] = []
    name = _form_file_name(case, _revision(case, approval))
    xml = case.get("verification_xml")
    if not xml:
        failures.append({"file": name, "reason": "no copy of the form the client was "
                                                 "sent is stored on the case"})
    else:
        try:
            files.append((name, await _render_form(case, entity, xml)))
        except Exception as exc:  # noqa: BLE001 — leave it off, say which and why
            failures.append({"file": name, "reason": str(exc)})

    if case.get("form_code") == "Nd2a":
        name = resolution.file_name(case)
        try:
            data = await officer_cases.composite(case["id"], user=None)
            files.append((name, await asyncio.to_thread(
                resolution.render, case, entity, data.get("entries") or [],
                data.get("officers") or [])))
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": name, "reason": str(exc)})
    return files, failures


async def send(case_id: str, approval: dict) -> None:
    """Mail the receipt for one claimed approval. Never raises."""
    try:
        recipient = (approval.get("recipient_email") or "").strip()
        if not recipient:
            print(f"[approval_receipt] approval {approval.get('id')} on case {case_id} "
                  "names no address; no receipt sent", file=sys.stderr)
            return
        case = nar1_cases.get_case(case_id)
        entity = nar1_cases.entity_for(case["entity_id"]) or {}
        files, failures = await documents(case, entity, approval)
        names = [name for name, _ in files]
        # Every document, by title — including one that would not render and
        # so is not in `names`.
        titles = [d["title"] for d in confirmed_documents(case, approval)]
        subject, html = email_service.approval_receipt_email(
            case, entity, form_code=case.get("form_code") or "Nar1",
            confirmed_by=approval.get("recipient_name"), confirmed_email=recipient,
            confirmed_at=approval.get("responded_at"),
            revision=_revision(case, approval), attachments=names, documents=titles)
        # The same three headers as the verification letter; outside
        # production `send` itself redirects the recipient and drops the copy.
        sent = await asyncio.to_thread(
            email_service.send, to=[recipient], cc=[email_service.CLIENT_CC],
            reply_to=email_service.CLIENT_CC, subject=subject, html=html,
            attachments=files)
    except Exception as exc:  # noqa: BLE001 — the approval is recorded; say so on stderr
        print(f"[approval_receipt] receipt for case {case_id} not sent: {exc!r}",
              file=sys.stderr)
        return

    try:
        await log_event(
            user_id=None, user_display_name=ACTOR,
            action_type=ev.EMAIL_SENT, event_code=ev.EMAIL_SENT,
            entity_type="nar1_case", entity_id=case["id"], case_id=case.get("entity_id"),
            company_name=entity.get("company_name"), **audit_subject.for_case(case),
            new_value=", ".join(sent.get("to") or [recipient]),
            # Identifiers only: the PDFs are the statutory forms themselves.
            metadata={
                "template": TEMPLATE,
                "approval_id": approval.get("id"),
                "confirmed_at": approval.get("responded_at"),
                "revision": _revision(case, approval),
                "message_id": sent.get("id"),
                "to": sent.get("to"),
                "intended_to": sent.get("intended_to"),
                "cc": sent.get("cc"),
                "intended_cc": sent.get("intended_cc"),
                "redirected": bool(sent.get("redirected")),
                "documents": titles,
                "attachments": names,
                "attachment_failures": failures,
            })
    except Exception as exc:  # noqa: BLE001 — audit never blocks (PBI-11)
        print(f"[approval_receipt] audit for case {case_id} failed: {exc!r}",
              file=sys.stderr)
