import sys
from typing import Optional, Any

from db.supabase import get_supabase
from services import audit_subject

_CREDENTIAL_KEYS = {
    "authorization", "password", "pin", "token", "secret",
    # TPSI: signature material is as sensitive as the password that made it.
    "eservice_password", "tpsi_password", "access_token",
    "usercredentialhash", "usersignature", "encryptionkey",
}

# code -> generic action name, from the audit_event_types registry (migration
# 012). Cached: the registry is small and effectively static at runtime.
_LABELS: Optional[dict[str, str]] = None


def _scrub(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    return {k: v for k, v in data.items() if k.lower() not in _CREDENTIAL_KEYS}


def action_label(event_code: Optional[str]) -> Optional[str]:
    """Generic action name for a code — the same name Viewpoint uses.

    Deliberately generic ("Change Master File Details"), never per-record
    ("Master File Details of Miss Ilze TSERKEZIS Changed"), so the same action
    groups and filters together across both systems.
    """
    global _LABELS
    if not event_code:
        return None
    if _LABELS is None:
        try:
            rows = (
                get_supabase().table("audit_event_types")
                .select("code, name").execute().data
            ) or []
            _LABELS = {r["code"]: r["name"] for r in rows}
        except Exception as exc:
            print(f"[audit_service] WARN: event-type registry unavailable: {exc}",
                  file=sys.stderr)
            _LABELS = {}
    return _LABELS.get(event_code)


def _build_row(
    *,
    user_id: str,
    user_display_name: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    case_id: Optional[str] = None,
    event_code: Optional[str] = None,
    company_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    metadata: Optional[dict] = None,
    module: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
) -> dict:
    row: dict[str, Any] = {
        "user_id": user_id,
        "user_display_name": user_display_name,
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": "g_flowdesk",
        # Which surface, and which record. Anything the caller stated wins; the
        # rest follows from entity_type, so a route that has nothing special to
        # say still writes a row the trail can name and link.
        **audit_subject.derive(
            entity_type=entity_type, case_id=case_id, entity_id=entity_id,
            module=module, subject_kind=subject_kind,
            subject_id=subject_id, subject_ref=subject_ref,
        ),
    }
    if case_id is not None:
        row["case_id"] = case_id
    if event_code is not None:
        row["event_code"] = event_code
        label = action_label(event_code)
        if label:
            row["action_label"] = label
    if company_name is not None:
        row["company_name"] = company_name
    if old_value is not None:
        row["old_value"] = str(old_value)
    if new_value is not None:
        row["new_value"] = str(new_value)
    if before_state is not None:
        row["before_state"] = before_state
    if after_state is not None:
        row["after_state"] = after_state
    if metadata is not None:
        row["metadata"] = _scrub(metadata)
    return row


async def log_events(events: list[dict]) -> None:
    """Insert several audit entries in ONE round trip.

    A form save changes several fields and each one is its own audit entry. Doing
    an insert per field meant a Supabase round trip (~200ms) per field, which is
    most of why saving felt slow. Never raises — failures go to stderr.
    """
    if not events:
        return
    try:
        rows = [_build_row(**e) for e in events]
        get_supabase().table("audit_log").insert(rows).execute()
    except Exception as exc:
        print(f"[audit_service] ERROR: failed to write audit log: {exc}", file=sys.stderr)


async def log_event(
    *,
    user_id: str,
    user_display_name: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    case_id: Optional[str] = None,
    event_code: Optional[str] = None,
    company_name: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    metadata: Optional[dict] = None,
    module: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
) -> None:
    """Insert one audit entry. Never raises — failures go to stderr.

    Every entry records the same context regardless of source: which module and
    which record (subject kind + id + name + reference), what action (event_code
    -> generic label), the old and new value, and who did it.

    The company/person name is denormalized so the trail stays readable after
    the record is deleted, and so it can be searched and sorted without a join.
    """
    try:
        row = _build_row(
            user_id=user_id, user_display_name=user_display_name,
            action_type=action_type, entity_type=entity_type,
            entity_id=entity_id, case_id=case_id, event_code=event_code,
            company_name=company_name, old_value=old_value, new_value=new_value,
            before_state=before_state, after_state=after_state,
            metadata=metadata, module=module, subject_kind=subject_kind,
            subject_id=subject_id, subject_ref=subject_ref,
        )
        get_supabase().table("audit_log").insert(row).execute()
    except Exception as exc:
        print(f"[audit_service] ERROR: failed to write audit log: {exc}", file=sys.stderr)
