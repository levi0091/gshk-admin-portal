import sys
from typing import Optional, Any

from db.supabase import get_supabase

_CREDENTIAL_KEYS = {"authorization", "password", "pin", "token", "secret"}

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
) -> dict:
    row: dict[str, Any] = {
        "user_id": user_id,
        "user_display_name": user_display_name,
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": "g_flowdesk",
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
) -> None:
    """Insert one audit entry. Never raises — failures go to stderr.

    Every entry records the same context regardless of source: which company
    (id + name), what action (event_code -> generic label), the old and new
    value, and who did it.
    """
    try:
        sb = get_supabase()
        row: dict[str, Any] = {
            "user_id": user_id,
            "user_display_name": user_display_name,
            "action_type": action_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source": "g_flowdesk",
        }
        if case_id is not None:
            row["case_id"] = case_id
        if event_code is not None:
            row["event_code"] = event_code
            label = action_label(event_code)
            if label:
                row["action_label"] = label
        # Denormalized so the trail stays readable even if the company is later
        # deleted, and so it can be searched/sorted without a join.
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

        sb.table("audit_log").insert(row).execute()
    except Exception as exc:
        print(f"[audit_service] ERROR: failed to write audit log: {exc}", file=sys.stderr)
