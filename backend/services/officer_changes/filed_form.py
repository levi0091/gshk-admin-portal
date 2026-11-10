"""The signed ND2A / ND2B, saved to the company's documents on the e-Sign route.

Levi 2026-10-18: "On the e-Sign route, the signed ND2A isn't saved to the
company's documents." The manual route's always was: the operator uploads the
form signed on CR's portal (`POST /officer-changes/{id}/signed-form`) and it is
stored on the COMPANY as type `nd2a` / `nd2b`. On the e-Sign route CR signed
and holds the form, and nothing reached the profile.

This renders CR's own copy (`validated_xml`, the one the Submission screen
showed before filing), full form with the PI sheets, dated the day CR received
it, and stores it where the manual route stores its upload, keeping the
(document id, version) pair on the case for the same reason that route does:
`upload_document` versions one row per company and type, so the id alone stops
pointing at this case's form at the company's next ND2A.

It NEVER raises. It runs after CR has the form, so a failure is reported beside
the filing and can be retried from the Confirmation stage.
"""
from __future__ import annotations

import asyncio
import sys

from services import document_service, nar1_cases
from services.officer_change_form import render as render_form
from services.officer_changes import signed_copies

_PREFIX = {"Nd2a": "ND2A", "Nd2b": "ND2B"}


async def save(case: dict, user: dict) -> dict:
    """`{"document_id", "version", "file_name"}`, or `{"error"}`."""
    try:
        filing = nar1_cases.current_filing(case["id"])
        xml = (filing or {}).get("validated_xml")
        if not xml:
            return {"error": "The signed form was not saved to the company's documents: "
                             "CR's copy of the form is not stored on the filing."}
        form = _PREFIX[case["form_code"]]
        entity = nar1_cases.entity_for(case["entity_id"]) or {}
        name = "  ".join(p for p in (entity.get("company_name"),
                                     entity.get("company_name_zh")) if p)
        pdf = await asyncio.to_thread(
            render_form, case["form_code"], xml, company_name=name, public_only=False,
            submitted_on=nar1_cases.filed_on(filing, case),
            signatures=signed_copies.for_form(case))
        case_no = case.get("case_no") or case["id"]
        file_name = f"{form}-{case_no}-signed.pdf"
        document = await document_service.upload_document(
            owner_kind="entity", owner_id=case["entity_id"],
            document_type_code=case["form_code"].lower(), file_name=file_name,
            content=pdf, mime_type="application/pdf",
            title=f"{case_no} — signed {form} (e-Sign)", user=user)
        version = document.get("current_version") or 1
        nar1_cases.update_case(case["id"], {"filed_form_document_id": document["id"],
                                            "filed_form_document_version": version})
        return {"document_id": document["id"], "version": version, "file_name": file_name}
    except Exception as exc:  # noqa: BLE001 — CR has the form; report, never raise
        print(f"[filed_form] case {case.get('id')}: {exc!r}", file=sys.stderr)
        return {"error": f"The signed form was not saved to the company's documents: {exc}"}
