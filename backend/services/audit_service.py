import sys
from typing import Optional, Any
from db.supabase import get_supabase

_CREDENTIAL_KEYS = {"authorization", "password", "pin", "token", "secret"}


def _scrub(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    return {k: v for k, v in data.items() if k.lower() not in _CREDENTIAL_KEYS}


async def log_event(
    *,
    user_id: str,
    user_display_name: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    case_id: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Insert one audit log entry. Never raises — failures are logged to stderr."""
    try:
        sb = get_supabase()
        row: dict[str, Any] = {
            "user_id": user_id,
            "user_display_name": user_display_name,
            "action_type": action_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        if case_id is not None:
            row["case_id"] = case_id
        if before_state is not None:
            row["before_state"] = before_state
        if after_state is not None:
            row["after_state"] = after_state
        if metadata is not None:
            row["metadata"] = _scrub(metadata)

        sb.table("audit_log").insert(row).execute()
    except Exception as exc:
        print(f"[audit_service] ERROR: failed to write audit log: {exc}", file=sys.stderr)
