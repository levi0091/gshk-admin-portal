"""Supporting documents held on an officer-change case until it is filed.

Levi, 2026-09-30 (answers 7, 11, 13): at Data Verification each joiner and
leaver gets an upload area — resignation letter, board resolution, consent to
act, other. The files are held under the CASE (`officer-change/{case}/{entry}/`)
and are not on anybody's profile yet: until the form is filed, the change has
not happened as far as CR is concerned, and a resignation letter on the profile
of a director who is still registered would say otherwise.

When the form is filed each file becomes a document on the OFFICER's own
profile — the person, or the body corporate's company record — through
`document_service.upload_document`, so it is versioned and audited like any
other upload (spec §6, B-2). The case keeps the pointer (id AND version, for
migration 023's reason: `upload_document` versions in place, so an id alone
stops naming this file at the next upload).
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone

from db.supabase import get_supabase
from services import document_service

SUPPORT_TYPES = ("resignation_letter", "board_resolution", "consent_to_act",
                 "officer_change_support")
#: A CASE-level document (Jacqueline A3) — the written resolution, or anything
#: else GSHK sends with the client email — belongs to the form, not to one
#: officer, and is filed to the COMPANY's profile.
CASE_TYPES = ("board_resolution", "officer_change_support")


class AttachmentError(RuntimeError):
    """A document ticked to go with the email could not be read from storage."""

    def __init__(self, file_name: str):
        self.file_name = file_name
        super().__init__(f"{file_name} could not be read from storage")
_TABLE = "officer_change_documents"
_SIGNED_URL_TTL = 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filed(case: dict) -> bool:
    return bool(case.get("changes_applied_at") or case.get("manual_receipt"))


def _labels() -> dict[str, str]:
    try:
        rows = (get_supabase().table("document_types").select("code,label")
                .in_("code", list(SUPPORT_TYPES)).execute().data) or []
    except Exception:  # noqa: BLE001 — a label is decoration
        rows = []
    out = {code: code.replace("_", " ").capitalize() for code in SUPPORT_TYPES}
    out.update({r["code"]: r["label"] for r in rows if r.get("label")})
    return out


def _company_of(case: dict | None, case_id: str | None = None) -> dict:
    """`{owner_kind: "entity", owner_id, name}` for the case's company."""
    entity_id = (case or {}).get("entity_id")
    if not entity_id and case_id:
        rows = (get_supabase().table("nar1_cases").select("*").eq("id", case_id)
                .execute().data) or []
        entity_id = rows[0].get("entity_id") if rows else None
    name = None
    if entity_id:
        rows = (get_supabase().table("entities").select("*").eq("id", entity_id)
                .execute().data) or []
        name = rows[0].get("company_name") if rows else None
    return {"owner_kind": "entity", "owner_id": entity_id, "name": name or "the company"}


def destination(entry: dict | None, *, case: dict | None = None) -> dict:
    """`{owner_kind: "person" | "entity", owner_id, name}` — the officer's own
    profile, or the company's for a case-level document."""
    if entry is None:
        return _company_of(case)
    name = ((entry.get("party") or {}).get("name")) or None
    if entry.get("person_id"):
        if name is None:
            rows = (get_supabase().table("persons").select("id,full_name")
                    .eq("id", entry["person_id"]).execute().data) or []
            name = rows[0].get("full_name") if rows else None
        return {"owner_kind": "person", "owner_id": entry["person_id"],
                "name": name or "(unnamed person)"}
    if name is None:
        rows = (get_supabase().table("entities").select("id,company_name")
                .eq("id", entry.get("corporate_entity_id")).execute().data) or []
        name = rows[0].get("company_name") if rows else None
    return {"owner_kind": "entity", "owner_id": entry.get("corporate_entity_id"),
            "name": name or "(unnamed body corporate)"}


async def upload(case: dict, entry: dict | None, *, document_type_code: str,
                 file_name: str, content: bytes, mime_type: str | None, user: dict | None,
                 send_with_email: bool = False) -> dict:
    """Hold a file on the case. `entry` None is a CASE-level document."""
    if entry is None:
        if document_type_code not in CASE_TYPES:
            raise ValueError("A document for the whole form is a written resolution "
                             "or other")
    elif document_type_code not in SUPPORT_TYPES:
        raise ValueError("A supporting document is a resignation letter, a board "
                         "resolution, a consent to act, or other")
    if not content:
        raise ValueError("The file is empty")
    if _filed(case):
        raise ValueError("This form has been filed; its supporting documents are on "
                         "the officers' profiles now")
    if entry is not None and entry.get("case_id") != case["id"]:
        raise ValueError("That entry is not on this case")
    sb = get_supabase()
    safe = (file_name or "file").replace("/", "_")
    folder = entry["id"] if entry is not None else "case"
    path = f"officer-change/{case['id']}/{folder}/{uuid.uuid4().hex[:12]}-{safe}"
    document_service._upload_bytes(sb, path, content, mime_type)
    return sb.table(_TABLE).insert({
        "case_id": case["id"], "entry_id": entry["id"] if entry is not None else None,
        "document_type_code": document_type_code, "file_name": safe,
        "storage_bucket": document_service.BUCKET, "storage_path": path,
        "mime_type": mime_type, "file_size_bytes": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
        "uploaded_by": (user or {}).get("id"), "uploaded_at": _now(),
        "send_with_email": bool(send_with_email),
    }).execute().data[0]


def _view(row: dict, entries_by_id: dict[str, dict], labels: dict[str, str],
          company: dict | None = None) -> dict:
    entry = entries_by_id.get(row.get("entry_id")) or {"person_id": None,
                                                        "corporate_entity_id": None}
    if row.get("entry_id") is None:
        where = company
    elif entry.get("person_id") or entry.get("corporate_entity_id"):
        where = destination(entry)
    else:
        where = None
    return {
        "id": row["id"], "entry_id": row.get("entry_id"),
        "document_type_code": row["document_type_code"],
        "type_label": labels.get(row["document_type_code"], row["document_type_code"]),
        "file_name": row["file_name"], "uploaded_at": row.get("uploaded_at"),
        "send_with_email": bool(row.get("send_with_email")),
        "destination": where,
        "filed": row.get("filed_at") is not None,
        "filed_document_id": row.get("filed_document_id"),
        "filed_document_version": row.get("filed_document_version"),
        "filed_at": row.get("filed_at"),
    }


def _rows(case_id: str) -> list[dict]:
    rows = get_supabase().table(_TABLE).select("*").eq("case_id", case_id).execute().data or []
    return sorted(rows, key=lambda r: r.get("uploaded_at") or "")


def _entries(case_id: str) -> list[dict]:
    return (get_supabase().table("officer_change_entries").select("*")
            .eq("case_id", case_id).execute().data) or []


def list_for_case(case_id: str, entries: list[dict] | None = None) -> list[dict]:
    """C-4 `DOC` rows."""
    rows = _rows(case_id)
    if not rows:
        return []
    by_id = {e["id"]: e for e in (entries if entries is not None else _entries(case_id))}
    labels = _labels()
    company = (_company_of(None, case_id) if any(r.get("entry_id") is None for r in rows)
               else None)
    return [_view(r, by_id, labels, company) for r in rows]


def set_send_with_email(case: dict, doc_id: str, value: bool) -> dict:
    """Tick or untick a case document to go with the verification email."""
    doc = get(case["id"], doc_id)
    if doc is None:
        raise LookupError(f"no document {doc_id} on case {case['id']}")
    return (get_supabase().table(_TABLE).update({"send_with_email": bool(value)})
            .eq("id", doc_id).execute().data[0])


def email_attachments(case_id: str) -> list[tuple[str, bytes]]:
    """`[(file_name, bytes)]` for every document ticked to go with the email.

    Raises `AttachmentError` naming the first file that cannot be read: the
    send must stop rather than mail a letter missing what it promises."""
    out = []
    sb = get_supabase()
    for row in _rows(case_id):
        if not row.get("send_with_email"):
            continue
        try:
            content = sb.storage.from_(row.get("storage_bucket")
                                       or document_service.BUCKET).download(row["storage_path"])
        except Exception as exc:  # noqa: BLE001 — named, then refused
            print(f"officer_change_documents: attachment {row['storage_path']} "
                  f"unreadable: {exc!r}", file=sys.stderr)
            raise AttachmentError(row["file_name"]) from exc
        out.append((row["file_name"], content))
    return out


def get(case_id: str, doc_id: str) -> dict | None:
    rows = (get_supabase().table(_TABLE).select("*").eq("id", doc_id)
            .eq("case_id", case_id).execute().data) or []
    return rows[0] if rows else None


def remove(case: dict, doc_id: str) -> dict:
    doc = get(case["id"], doc_id)
    if doc is None:
        raise LookupError(f"no document {doc_id} on case {case['id']}")
    if doc.get("filed_at"):
        raise ValueError("This document has been saved to the officer's profile; "
                         "remove it there")
    sb = get_supabase()
    sb.table(_TABLE).delete().eq("id", doc_id).execute()
    try:
        sb.storage.from_(doc.get("storage_bucket") or document_service.BUCKET).remove(
            [doc["storage_path"]])
    except Exception as exc:  # noqa: BLE001 — an orphaned object is harmless
        print(f"officer_change_documents: could not remove {doc['storage_path']}: "
              f"{exc!r}", file=sys.stderr)
    return doc


def signed_url(doc: dict) -> str:
    signed = get_supabase().storage.from_(
        doc.get("storage_bucket") or document_service.BUCKET).create_signed_url(
        doc["storage_path"], _SIGNED_URL_TTL, options={"download": doc.get("file_name")})
    return signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")


async def file_to_profiles(case: dict, entries: list[dict], *, user: dict) -> list[dict]:
    """File every unfiled document onto its officer's profile. Never raises.

    Runs after CR has the form, so a failure here must not read as a failed
    filing: each document is tried on its own, reported with its `error`, and a
    second call files what the first could not and skips what it did.
    """
    out = []
    try:
        rows = _rows(case["id"])
        labels = _labels()
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"could not read the case's documents: {exc}"}]
    by_id = {e["id"]: e for e in entries}
    sb = get_supabase()
    for row in rows:
        company = _company_of(case) if row.get("entry_id") is None else None
        view = _view(row, by_id, labels, company)
        if row.get("filed_at"):
            out.append({**view, "error": None})
            continue
        try:
            if row.get("entry_id") is None:
                dest = company
            else:
                entry = by_id.get(row["entry_id"])
                if entry is None:
                    raise LookupError("its entry is no longer on the case")
                dest = destination(entry)
            content = sb.storage.from_(row.get("storage_bucket")
                                       or document_service.BUCKET).download(row["storage_path"])
            title = f"{case.get('case_no') or 'Officer change'} — {view['type_label']}"
            doc = await document_service.upload_document(
                owner_kind=dest["owner_kind"], owner_id=dest["owner_id"],
                document_type_code=row["document_type_code"], file_name=row["file_name"],
                content=content, mime_type=row.get("mime_type"), title=title, user=user)
            stamp = {"filed_document_id": doc["id"],
                     "filed_document_version": doc.get("current_version"),
                     "filed_at": _now()}
            sb.table(_TABLE).update(stamp).eq("id", row["id"]).execute()
            out.append({**_view({**row, **stamp}, by_id, labels, company), "error": None})
        except Exception as exc:  # noqa: BLE001 — see docstring
            detail = getattr(exc, "detail", None) or str(exc)
            print(f"officer_change_documents: filing {row['id']} failed: {detail}",
                  file=sys.stderr)
            out.append({**view, "error": str(detail)})
    return out
