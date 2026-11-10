"""The manual checks an ND2A needs before it leaves Data Verification.

Jacqueline, 1 October 2026 (A4, and the mock-up on page 25): "Things the
portal cannot confirm for you. Tick them once they are genuinely done." What
remains of her list is the KYC of each incoming officer.

  * The written resolution is no longer a check: G-FlowDesk builds it from
    GSHK's own sample and sends it to the client WITH the ND2A.
  * Consent to act is no longer a check: CR's consent signature over the
    director's appointment, PIN-signed from their own e-Registry account, IS
    the consent (TPSI API v1.0.14 section 7.1.2). Without that account the
    form is filed on CR's portal, outside G-FlowDesk.
  * A resignation letter on file is no longer a check (Levi 2026-10-29, ND2
    change request 5). It used to gate leaving Data Verification for every
    leaver but a death; GSHK does not want the portal to hold the filing back
    over it. The upload and download routes, the `resignation_letter` document
    type and any letter already uploaded are untouched -- they stay on the
    officer's profile; only the GATE is gone.

DERIVED, never stored: the KYC check is the existing tick, so there is nothing
that can say "done" while it was never made.

  * A cessation raises no check at all.
  * An ND2B changes nobody's appointment: no checks.

Pure: the caller passes the case, the entries (each with `party.name`) and the
case's documents. `docs` and `route` are accepted for the callers' sake; no
check depends on either any more.
"""
from __future__ import annotations


def manual_checks(case: dict, entries: list[dict], docs: list[dict], *,
                  route: str) -> list[dict]:
    """`[{code, entry_id, label, kind, document_type, ok, document}]`: one KYC
    tick per appointment, in entry order."""
    if case.get("form_code") != "Nd2a" or not entries:
        return []

    def name(entry):
        return (entry.get("party") or {}).get("name") or "this officer"

    return [
        {"code": "kyc", "entry_id": entry["id"],
         "label": f"KYC / WorldCheck cleared — {name(entry)}",
         "kind": "tick", "document_type": None,
         "ok": bool(entry.get("kyc_cleared")), "document": None}
        for entry in entries if entry.get("kind") == "appointment"
    ]


def incomplete(items: list[dict]) -> list[str]:
    """The labels still open, in order."""
    return [i["label"] for i in items if not i["ok"]]
