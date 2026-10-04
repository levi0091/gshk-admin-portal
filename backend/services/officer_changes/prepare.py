"""Case + entries -> CR's ND2A / ND2B XML, and the consent-signature plan.

The one place the router asks for a form. It loads the graph, settles the
signing capacity the way NAR1 does (the operator's choice stored on the case,
else CR's usual arrangement — GSHK Ltd is the secretary and a GSHK director
signs for it), runs the form's mapper and builds the XML.

`for_esign=True` is what Data Verification passes before validating with CR:
every e-Registry account the filing needs must then be present. Anything else
— the client's preview, the manual route's PDF — only needs the particulars.
"""
from __future__ import annotations

from db.supabase import get_supabase
from services.officer_changes import eservice, form_xml, nd2a_mapper, nd2b_mapper, source
from services.tpsi.forms import nar1_mapper
from services.tpsi.forms.cr_vocabularies import (
    HKG, default_capacity, display_country, resolve_country,
)
from services.tpsi.forms.nar1_mapper import MappingError

__all__ = ["MappingError", "build_form_xml", "mapping_problems", "consent_plan"]

_MAPPERS = {"Nd2a": nd2a_mapper.map_case, "Nd2b": nd2b_mapper.map_case}


def _capacity(graph: dict, case: dict) -> str | None:
    if case.get("signatory_capacity"):
        return case["signatory_capacity"]
    try:
        resolved = nar1_mapper._derive_signatory(graph)
    except Exception:  # noqa: BLE001 — the mapper reports a thin graph itself
        resolved = None
    if not resolved:
        return None
    return default_capacity(is_corporate=resolved.get("is_corporate") is True)


async def build_form_xml(case: dict, entries: list[dict], *,
                         signing_identity: dict | None = None,
                         for_esign: bool = False,
                         require_dates: bool | None = None) -> str:
    """The form model XML for this case. Raises `MappingError` listing every
    problem at once — a length CR would refuse included."""
    graph = await source.load_graph(case["entity_id"], entries)
    data = _MAPPERS[case["form_code"]](
        graph, entries, signatory_capacity=_capacity(graph, case),
        signing_identity=signing_identity, for_esign=for_esign, require_dates=require_dates)
    try:
        return form_xml.build(case["form_code"], data)
    except form_xml.FormValidationError as exc:
        raise MappingError(exc.problems()) from exc


async def mapping_problems(case: dict, entries: list[dict]) -> list[str]:
    """Why the form cannot be built yet; `[]` when it can. Never raises."""
    try:
        await build_form_xml(case, entries)
        return []
    except MappingError as exc:
        return list(exc.problems)
    except Exception as exc:  # noqa: BLE001 — a loader failure is still a reason
        return [f"The form could not be prepared: {exc}"]


async def consent_plan(case: dict, entries: list[dict]) -> list[dict]:
    """One row per NEW DIRECTOR appointment, in entry order, matching the
    `id="S<n>"` the mapper puts on its bean. Empty for every ND2B: CR's
    interface asks for a consent signature on a director's appointment and on
    nothing else (spec §5)."""
    if case.get("form_code") != "Nd2a":
        return []
    directors = [e for e in entries
                 if e.get("kind") == "appointment" and e.get("capacity") == "director"]
    if not directors:
        return []
    signers = [e.get("consent_person_id") or e.get("person_id") for e in directors]
    accounts = eservice.metadata_for([s for s in signers if s])
    names = _names([s for s in signers if s])
    corps = _corporates([e.get("corporate_entity_id") for e in directors
                         if not e.get("person_id")])
    docs = _identity_documents([s for s in signers if s])
    plan = []
    for n, (entry, signer) in enumerate(zip(directors, signers), 1):
        account = accounts.get(signer) or {}
        name = names.get(signer) or "the consent signer"
        corp_id = None if entry.get("person_id") else entry.get("corporate_entity_id")
        overseas = _not_hong_kong(corps.get(corp_id) or {"id": corp_id}) if corp_id else None
        if overseas:
            reason = overseas
        elif not signer:
            reason = "Choose who signs the body corporate's consent"
        elif not account.get("eservice_user_id"):
            # Levi 2026-10-05: no account (or the director will not have GSHK
            # sign for them) means CR's portal, outside G-FlowDesk.
            reason = (f"{name} has no e-Registry account stored on their profile "
                      "— file this ND2A on the manual route (CR portal)")
        elif not account.get("eservice_person_name"):
            reason = f"The name on {name}'s e-Registry account is not recorded"
        elif not account.get("has_password"):
            reason = f"{name}'s e-Registry password is not stored"
        else:
            reason = None
        plan.append({
            "entry_id": entry["id"], "bean_id": f"S{n}", "signer_person_id": signer,
            "signer_name": name, "eservice_user_id": account.get("eservice_user_id"),
            "ready": reason is None, "reason": reason,
            "signed_at": entry.get("consent_signed_at"),
            # A warning, not a refusal: CR decides (Jacqueline, note 1).
            "id_mismatch": eservice.identity_mismatch(
                account, docs.get(signer, []), name=name) if signer else None,
        })
    return plan


def is_hong_kong_company(corp: dict) -> bool:
    """e-Registry takes a body-corporate director's consent only for a Hong
    Kong company (Brian, 2026-10-01: "the concept is similar to the authorised
    signer of NAR1"). Its country of incorporation, else — with none recorded —
    a CR number, which only a Hong Kong company has."""
    place = (corp or {}).get("incorporation_place")
    if place and str(place).strip():
        return resolve_country(str(place)) == HKG
    return bool(str((corp or {}).get("cr_number") or "").strip())


def _not_hong_kong(corp: dict) -> str | None:
    if is_hong_kong_company(corp):
        return None
    name = corp.get("company_name") or "this body corporate"
    place = str(corp.get("incorporation_place") or "").strip()
    where = (f"is incorporated in {display_country(resolve_country(place) or place)}"
             if place else "has no country of incorporation recorded")
    return (f"e-Registry accepts a body-corporate director's consent only for a Hong "
            f"Kong company — {name} {where}. File this ND2A on the manual route.")


def _corporates(entity_ids: list[str]) -> dict[str, dict]:
    ids = sorted({i for i in entity_ids if i})
    if not ids:
        return {}
    rows = (get_supabase().table("entities").select("*").in_("id", ids)
            .execute().data) or []
    return {r["id"]: r for r in rows}


def _identity_documents(person_ids: list[str]) -> dict[str, list[dict]]:
    ids = sorted({i for i in person_ids if i})
    if not ids:
        return {}
    rows = (get_supabase().table("person_identity_documents").select("*")
            .in_("person_id", ids).execute().data) or []
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row["person_id"], []).append(row)
    return out


def _names(person_ids: list[str]) -> dict[str, str]:
    if not person_ids:
        return {}
    rows = (get_supabase().table("persons").select("id,full_name")
            .in_("id", sorted(set(person_ids))).execute().data) or []
    return {r["id"]: r.get("full_name") for r in rows}
