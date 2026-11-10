"""ND2A / ND2B with several signing directors: who has signed, and sending to one
director at a time (nd2-multi-signer, spec 2.3 and 3.1).

Levi 2026-10-29: "we should see 2 separate sending features and the signatures
should converge once all are collected." With the option on
(`nar1_cases.multi_signer`), the Client Verification stage shows one panel per
required director, each with its own address, its own Send and its own status;
the case counts as client-approved only when every one of them has signed (that
convergence is `services/officer_changes/signers.record_signing`, run by the
public page, not here).

Two routes, both under `/officer-changes/{id}/verification`:

  GET  signers                       `officer_changes:read`  -- the report
  POST signers/{person_id}/send      `officer_changes:write` -- send to one director

THE FIRST SEND OF A ROUND does what the single send does -- builds the form,
creates or rebuilds the CR filing, takes the next revision, clears any earlier
answer -- and FREEZES the signer set it checked. Every later send in the round,
to another director or a re-send to the same one, mails the frozen XML under the
same revision, retires only that director's earlier link and writes nothing to
the case. The letter is built by the same helpers the single send uses
(`routers.officer_changes._letter_files` / `_mail` / `_audit_send`), so the two
cannot drift.

A multi-signer letter without a link is useless: the director cannot sign by
replying. So where the single send falls back to the reply path when a link
cannot be issued, this refuses with 503 and mails nothing.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from middleware.auth import require_permission
from routers import cases as nar1_router
from routers.officer_changes import (
    MODULE, _audit_send, _consent_wording, _filing_for_send, _letter_files, _mail,
    _problems, audit, filed, load_case, refuse_if_closed,
)
from services import audit_events as ev
from services import email_service, nar1_approvals, nar1_cases
from services.officer_changes import cases as svc, prepare, signers

router = APIRouter()


# -- the report ---------------------------------------------------------------------------

_UNKNOWN = {"status": "unknown",
            "detail": "no record of this letter's delivery was found"}


def _redirected_detail(entry: dict) -> str:
    """NAR1's sentence (routers.cases.verification_delivery), for the same
    reason: outside production the recipient lock sends every message to the
    internal test mailboxes, so Resend's record describes THEIR mailboxes and
    printing its "delivered" beside the director's address would be a lie."""
    went_to = ", ".join(entry.get("delivered_to") or []) or "the internal test recipients"
    return (f"nothing was sent to this address — this is a test environment, so "
            f"the message went to {went_to} instead")


async def _verdict(entry: dict | None, *, ask: bool) -> dict:
    """One director's delivery verdict: `{status, detail}`.

    A redirected message is NEVER asked about. Uncertainty -- a timeout, a
    fault, an answer Resend gives that we do not know -- is `pending`, never
    `failed`: telling an operator a letter bounced when it did not has them
    re-send a statutory notice to a director who already holds it.
    """
    if entry is None:
        return dict(_UNKNOWN)
    if entry.get("redirected"):
        return {"status": "redirected", "detail": _redirected_detail(entry)}
    if not ask:
        return {"status": "pending", "detail": "waiting for the mail server to answer"}
    try:
        answer = await asyncio.to_thread(
            email_service.delivery_status, entry.get("message_id"))
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[officer_change_signers] delivery check failed: {exc!r}", file=sys.stderr)
        return {"status": "pending", "detail": "could not check delivery just now"}
    status = answer.get("status")
    if status not in ("delivered", "failed", "pending"):
        status = "pending"
    return {"status": status, "detail": answer.get("detail")}


async def _with_delivery(case: dict, report: dict, *, sends: dict | None = None,
                         ask: bool = True) -> dict:
    """Layer each SENT director's delivery verdict onto `signers.state`.

    Only signers whose status is `sent` are looked at: a signed director has no
    use for a delivery verdict, and a director not yet sent has nothing to ask
    about. A `failed` verdict turns the status into `not_delivered`; a
    `redirected` one into `redirected`; everything else leaves it `sent` with the
    verdict beside it. Resend is asked for all of them concurrently, each on a
    worker thread, because these are blocking HTTP calls in an async handler.
    """
    pending = [s for s in report["signers"] if s["status"] == "sent"]
    if not pending:
        return report
    if sends is None:
        sends = signers.latest_sends(case)
    verdicts = await asyncio.gather(
        *[_verdict(sends.get(s["person_id"]), ask=ask) for s in pending])
    for signer, verdict in zip(pending, verdicts):
        signer["delivery"] = verdict
        if verdict["status"] == "redirected":
            signer["status"] = "redirected"
        elif verdict["status"] == "failed":
            signer["status"] = "not_delivered"
    return report


@router.get("/{case_id}/verification/signers")
async def list_signers(case_id: str,
                       user=Depends(require_permission(MODULE, "read"))):
    """Who must sign, who has been sent a link, who has signed, and whether the
    letters arrived. Changes nothing; asks Resend only about directors who were
    sent a link and have not signed."""
    case = load_case(case_id)
    return await _with_delivery(case, signers.state(case))


# -- sending to one director -----------------------------------------------------------------

class SignerSendIn(BaseModel):
    class Config:
        extra = "forbid"

    email: str
    respond_by: str | None = None


def _refuse(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status, {"message": message, "reason": reason})


def _shares_an_address(rows: list[dict], person_id: str, email: str) -> bool:
    """Is `email` already the address of ANOTHER required director's link?

    A drawn signature is personal. Two directors on one address would let the
    person who reads that inbox sign for both, so it is refused (conductor's
    decision on question Q1, 2026-10-29). A signed director's address counts as
    well as a live one: the person who signed from that inbox could otherwise
    sign again, as somebody else.
    """
    wanted = email.strip().lower()
    for row in rows:
        if row.get("person_id") == person_id:
            continue
        if (row.get("recipient_email") or "").strip().lower() != wanted:
            continue
        if row.get("outcome") == nar1_approvals.OUTCOME_APPROVED:
            return True
        if row.get("outcome") is None and not nar1_approvals.is_expired(row):
            return True
    return False


# The path segment is the director's person id, but it is NAMED `signer_id` on
# purpose: `tests/test_soft_delete.py` sweeps every route on a `{person_id}` path
# and requires it to refuse a deleted person. This route must not -- a director
# deleted from the register after the round froze still has to be able to sign,
# and the frozen set (not the live profile) decides who may be sent a link.
@router.post("/{case_id}/verification/signers/{signer_id}/send")
async def send_to_signer(case_id: str, signer_id: str, body: SignerSendIn,
                         request: Request,
                         user=Depends(require_permission(MODULE, "write"))):
    """Mail ONE required director a link of their own (spec 2.3)."""
    person_id = signer_id
    case = load_case(case_id)

    # -- 1. refusals, before anything is built -------------------------------------------
    if not case.get("multi_signer"):
        raise _refuse(409, "multi_signer_off",
                      "Directors are not signing separately on this form. Turn on "
                      "\"Multiple directors must sign\" first.")
    refuse_if_closed(case, "mailing a director")
    if filed(case):
        raise _refuse(409, "already_filed", "This form has been filed.")

    first = not signers.round_open(case)
    # ONE read of the set, used both to check the director and (on the first
    # send) to freeze: reading it twice would let a fault on the second read
    # freeze [] and strand the round for good (review A, S5).
    signer_list, frozen = signers.signer_set(case)
    if not first and (not frozen or not case.get("verification_xml")):
        raise _refuse(409, "round_not_fixed",
                      "This round has no fixed list of directors. Restart "
                      "verification, then send to each director again.")
    chosen = next((s for s in signer_list if s["person_id"] == person_id), None)
    if chosen is None:
        raise _refuse(409, "not_a_signer",
                      "This person is not one of the directors who must sign this form."
                      + (" Restart verification to ask the current directors."
                         if not first else ""))

    # An earlier revision's rows say nothing about a round that has not opened.
    rows = [] if first else signers.round_approvals(case)
    if any(r.get("person_id") == person_id
           and r.get("outcome") == nar1_approvals.OUTCOME_APPROVED for r in rows):
        raise _refuse(409, "signed", "This director has already signed. Restart "
                                     "verification to change the form.")
    answer = case.get("client_approved")
    if answer is True and case.get("client_approval_source") != nar1_approvals.SOURCE_STAFF_WAIVER:
        raise _refuse(409, "converged", "Every director has signed. Restart "
                                        "verification to change the form.")
    if answer is False:
        raise _refuse(409, "declined", "The client declined this form. Restart "
                                       "verification to send a new one.")

    data = await svc.composite(case_id, user=user)
    if data["rules"]["blocking"]:
        failing = [c["text"] for c in data["rules"]["checks"]
                   if not c["ok"] and c.get("level") == "rule"]
        raise _refuse(409, "rules_blocking", "Nothing was sent: " + " ".join(failing))

    # -- 2. the address ----------------------------------------------------------------------
    deadline_at = nar1_router._deadline_from(body.respond_by)
    address = (body.email or "").strip()
    if not nar1_router._ADDRESS.match(address):
        raise HTTPException(422, f"Nothing was sent: {address or '(blank)'} is not a "
                                 "valid email address")
    if _shares_an_address(rows, person_id, address):
        raise _refuse(409, "address_in_use",
                      f"{address} is already another director's address on this form. "
                      "Each director signs from their own email.")
    dead = await nar1_router._undeliverable([address])
    if dead:
        raise HTTPException(422, f"Nothing was sent: {address} cannot receive mail "
                                 f"({dead.get(address) or 'unreachable'})")
    link_base = nar1_router._approval_link_base(request)
    if not link_base:
        raise _refuse(503, "links_unavailable",
                      "A link for the director could not be made, so nothing was sent.")

    # -- 3. the letter -------------------------------------------------------------------------
    entries = svc.list_entries(case_id)
    superseded = 0
    if first:
        try:
            xml = await prepare.build_form_xml(case, entries)
        except prepare.MappingError as exc:
            raise _problems(exc)
        filing, superseded = _filing_for_send(case, xml, user)
        revision = nar1_approvals.next_revision(case)
    else:
        # The form the other directors hold. Rebuilding it now would hand this
        # director a different document under the same revision.
        xml = case["verification_xml"]
        filing = nar1_cases.current_filing(case_id)
        revision = nar1_approvals.current_revision(case)
    files = await _letter_files(case, data, xml, filing, revision)
    names = [name for name, _ in files]
    consents = await _consent_wording(case, entries)

    # -- 4. the link -----------------------------------------------------------------------------
    if first:
        try:
            nar1_approvals.supersede_outstanding(case_id)
        except Exception as exc:  # noqa: BLE001 — leftovers are for an earlier revision anyway
            print(f"[officer_change_signers] could not clear earlier links on "
                  f"{case_id}: {exc}", file=sys.stderr)
    try:
        target = nar1_approvals.issue_for_signer(
            case_id=case_id, recipient={"email": address, "person_id": person_id,
                                        "name": chosen.get("name")},
            revision=revision, expires_at=deadline_at)
    except Exception as exc:  # noqa: BLE001
        print(f"[officer_change_signers] approval token not issued for {case_id}: {exc}",
              file=sys.stderr)
        raise _refuse(503, "links_unavailable",
                      "A link for the director could not be made, so nothing was sent.")

    # -- 5. send -----------------------------------------------------------------------------------
    entity = nar1_cases.entity_for(case["entity_id"]) or {}
    respond_day = deadline_at.astimezone(nar1_router._HK).date()
    sends, failures = await _mail(case, entity, data, [target], link_base, revision,
                                  respond_day, files, consents)
    if not sends:
        raise HTTPException(502, "The verification email was not sent: "
                                 + ("; ".join(f["reason"] for f in failures)
                                    or "no recipients"))

    # -- 6. store (the first send of a round only) ------------------------------------------------
    sent_at = datetime.now(timezone.utc).isoformat()
    previous = case.get("client_approved")
    cleared = False
    if first:
        patch = {"verification_sent_at": sent_at, "verification_xml": xml,
                 "verification_revision": revision,
                 # The list that was CHECKED above, never a second read of it.
                 "required_signers": signers.freeze(signer_list)}
        if previous is not None or case.get("client_response_at"):
            cleared = True
            patch.update(client_approved=None, client_response_at=None,
                         client_approval_source=None, client_approval_person_id=None,
                         client_approval_name=None)
        nar1_cases.update_case(case_id, patch)
        try:
            svc.mark_deferred(case_id)
        except Exception as exc:  # noqa: BLE001 — the mail is out; say so on stderr
            print(f"[officer_change_signers] mark_deferred failed for {case_id}: {exc!r}",
                  file=sys.stderr)

    # -- 7. audit --------------------------------------------------------------------------------------
    report = await _audit_send(
        case, user, sends, failures, revision=revision, deadline_at=deadline_at,
        names=names, superseded=superseded, person_ids=True,
        extra_metadata={"signer_person_id": person_id, "multi_signer": True,
                        "round_opened": first})
    if cleared:
        await audit(case, user, ev.CASE_STATUS_CHANGED,
                    old_value="approved" if previous else "rejected",
                    new_value="awaiting_client",
                    metadata={"reason": "a fresh verification superseded the previous answer"})

    # -- 8. response -----------------------------------------------------------------------------------
    signer = None
    try:
        fresh = signers.state(load_case(case_id))
        await _with_delivery(case, fresh, ask=False, sends={
            person_id: report["deliveries"][0]})
        signer = next((s for s in fresh["signers"] if s["person_id"] == person_id), None)
    except Exception as exc:  # noqa: BLE001 — the mail is out; a report is only an extra
        print(f"[officer_change_signers] could not read the signer back on {case_id}: "
              f"{exc!r}", file=sys.stderr)
    return {"sent_at": sent_at, "revision": revision, "round_opened": first,
            "person_id": person_id, "to": report["delivered"],
            "intended_to": report["intended"], "redirected": report["redirected"],
            "message_ids": report["message_ids"], "deliveries": report["deliveries"],
            "failed": failures, "respond_by": deadline_at.isoformat(), "signer": signer}
