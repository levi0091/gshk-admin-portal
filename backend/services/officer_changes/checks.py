"""The manual checks an ND2A needs before it leaves Data Verification.

Jacqueline, 1 October 2026 (A4, and the mock-up on page 25): "Things the
portal cannot confirm for you. Tick them once they are genuinely done." What
remains of her list (Levi 2026-10-05) is the KYC of each incoming officer and a
resignation letter on file for each leaver.

  * The written resolution is no longer a check: G-FlowDesk builds it from
    GSHK's own sample and sends it to the client WITH the ND2A.
  * Consent to act is no longer a check: CR's consent signature over the
    director's appointment, PIN-signed from their own e-Registry account, IS
    the consent (TPSI API v1.0.14 section 7.1.2). Without that account the
    form is filed on CR's portal, outside G-FlowDesk.

DERIVED, never stored: a letter check is done when a document of its type is
attached to that entry, and the KYC check is the existing tick. So there is
nothing that can say "done" while the file is missing, or "missing" after it
was attached.

  * A death needs no resignation letter.
  * An ND2B changes nobody's appointment: no checks.

Pure: the caller passes the case, the entries (each with `party.name`) and the
case's documents. `route` is accepted for the callers' sake; no check depends
on it any more.
"""
from __future__ import annotations


def _latest(docs: list[dict], document_type: str, entry_id) -> dict | None:
    """The newest document of a type on one entry."""
    found = [d for d in docs if d.get("document_type_code") == document_type
             and d.get("entry_id") == entry_id]
    if not found:
        return None
    best = max(found, key=lambda d: d.get("uploaded_at") or "")
    return {"id": best.get("id"), "file_name": best.get("file_name"),
            "uploaded_at": best.get("uploaded_at")}


def manual_checks(case: dict, entries: list[dict], docs: list[dict], *,
                  route: str) -> list[dict]:
    """`[{code, entry_id, label, kind, document_type, ok, document}]`, in the
    order the mock-up lists them: KYC, then resignation letters."""
    if case.get("form_code") != "Nd2a" or not entries:
        return []

    def name(entry):
        return (entry.get("party") or {}).get("name") or "this officer"

    kyc, letters = [], []
    for entry in entries:
        if entry.get("kind") == "appointment":
            kyc.append({"code": "kyc", "entry_id": entry["id"],
                        "label": f"KYC / WorldCheck cleared — {name(entry)}",
                        "kind": "tick", "document_type": None,
                        "ok": bool(entry.get("kyc_cleared")), "document": None})
        elif entry.get("kind") == "cessation" and entry.get("cessation_reason") != "D":
            document = _latest(docs, "resignation_letter", entry["id"])
            letters.append({"code": "resignation_letter", "entry_id": entry["id"],
                            "label": f"Resignation letter on file — {name(entry)}",
                            "kind": "document", "document_type": "resignation_letter",
                            "ok": document is not None, "document": document})
    return kyc + letters


def incomplete(items: list[dict]) -> list[str]:
    """The labels still open, in order."""
    return [i["label"] for i in items if not i["ok"]]
