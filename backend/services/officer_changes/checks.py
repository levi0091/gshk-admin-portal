"""The manual checks an ND2A needs before it leaves Data Verification.

Jacqueline, 1 October 2026 (A4, and the mock-up on page 25): "Things the
portal cannot confirm for you. Tick them once they are genuinely done." Her
list is the KYC of each incoming officer, a resignation letter on file for each
leaver, the board's written resolution ("for any change of director or company
secretary, the company must sign an additional written resolution") and, from
A2, the new director's consent to act ("we must collect the signed page 2
before submitting the form to CR").

DERIVED, never stored: a document check is done when a document of its type is
attached, and the KYC check is the existing tick. So there is nothing that can
say "done" while the file is missing, or "missing" after it was attached.

  * The consent check applies on the MANUAL route only. On e-Sign, CR's own
    consent signature — applied from the director's e-Registry account — is the
    consent, and asking for a second one would be paperwork for its own sake.
  * A death needs no resignation letter.
  * An ND2B changes nobody's appointment: no KYC, no resolution, no letter.

Pure: the caller passes the case, the entries (each with `party.name`) and the
case's documents.
"""
from __future__ import annotations


def _latest(docs: list[dict], document_type: str, entry_id=..., *,
            kept_only: bool = False) -> dict | None:
    """The newest document of a type — on one entry, or (default) anywhere.
    `kept_only` ignores a document ticked to go with the client email: that
    copy is the draft sent out for signature (review finding 2)."""
    found = [d for d in docs if d.get("document_type_code") == document_type
             and (entry_id is ... or d.get("entry_id") == entry_id)
             and not (kept_only and d.get("send_with_email"))]
    if not found:
        return None
    best = max(found, key=lambda d: d.get("uploaded_at") or "")
    return {"id": best.get("id"), "file_name": best.get("file_name"),
            "uploaded_at": best.get("uploaded_at")}


def _document_check(code: str, label: str, document_type: str, entry_id,
                    document: dict | None) -> dict:
    return {"code": code, "entry_id": entry_id, "label": label, "kind": "document",
            "document_type": document_type, "ok": document is not None,
            "document": document}


def manual_checks(case: dict, entries: list[dict], docs: list[dict], *,
                  route: str) -> list[dict]:
    """`[{code, entry_id, label, kind, document_type, ok, document}]`, in the
    order the mock-up lists them: KYC, resignation letters, consents, then the
    case's written resolution."""
    if case.get("form_code") != "Nd2a" or not entries:
        return []

    def name(entry):
        return (entry.get("party") or {}).get("name") or "this officer"

    kyc, letters, consents = [], [], []
    for entry in entries:
        if entry.get("kind") == "appointment":
            kyc.append({"code": "kyc", "entry_id": entry["id"],
                        "label": f"KYC / WorldCheck cleared — {name(entry)}",
                        "kind": "tick", "document_type": None,
                        "ok": bool(entry.get("kyc_cleared")), "document": None})
            if route == "manual" and entry.get("capacity") == "director":
                consents.append(_document_check(
                    "consent_to_act", f"Consent to act signed — {name(entry)}",
                    "consent_to_act", entry["id"],
                    _latest(docs, "consent_to_act", entry["id"])))
        elif entry.get("kind") == "cessation" and entry.get("cessation_reason") != "D":
            letters.append(_document_check(
                "resignation_letter", f"Resignation letter on file — {name(entry)}",
                "resignation_letter", entry["id"],
                _latest(docs, "resignation_letter", entry["id"])))
    resolution = _document_check("written_resolution", "Signed written resolution on file",
                                 "board_resolution", None,
                                 _latest(docs, "board_resolution", kept_only=True))
    return kyc + letters + consents + [resolution]


def incomplete(items: list[dict]) -> list[str]:
    """The labels still open, in order."""
    return [i["label"] for i in items if not i["ok"]]
