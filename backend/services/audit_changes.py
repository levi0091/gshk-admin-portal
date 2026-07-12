"""Decode what actually changed in a Viewpoint audit event.

Viewpoint packs an event into EventLog.EventString as one key=value blob. Most
of it is unchanged context; the changes are hidden in two conventions:

    Field=new|old        the pipe separates the new value from the old one
    OldField= / NewField=   an explicit pair

Both were verified against the live EventLog: on 3,494 events carrying both
forms, the pipe halves and the Old/New pair agreed every time, with no
disagreements. So the pipe is safe to read as new|old.

Everything else in the blob is context, not change. Reading the blob raw is why
the trail was unusable -- an address move showed as twenty near-identical
internal flags and the one real change was buried.

Events that change nothing (a form was generated, a master file was created)
have no pair to extract, so we surface the fields that say WHAT happened
instead -- for a form generation, which form.
"""
import re

# Viewpoint's internal document/checklist bookkeeping. These flip on almost
# every event and mean nothing to a user: "Di1chkD", "SCxchkS", "VPC.SEV7".
# They are the noise, not the signal.
_NOISE_EXACT = {
    "MergedChangeNumber", "LinkedChangeNumbers", "ChangeMode", "EventNr",
    "PRIV", "OTHR", "RS", "RmcRCR", "RxcRCR", "ImcCON", "ImcCOY", "RmcCON",
    "IxcCON", "RxcCON", "CmcCON",
}
_NOISE_PATTERN = re.compile(r"chk|^VPC\.|^ALLOTLIST", re.IGNORECASE)

# Identifiers that locate the event rather than describe a change.
_KEYS = {"EntCode", "RefCode", "AddrCode", "KeyCode"}

# What to show for events that record an action rather than a field edit.
# The field names are Viewpoint's and are not consistent between event codes
# (a form queue number is FQnumber in one and FQNumber in another) — both spellings
# are listed rather than normalised, so the lookup stays a plain dict get.
_SUMMARY_FIELDS = {
    "SFMG": ("FormName", "FQnumber", "FQNumber"),   # form generated
    "SWRG": ("ReportName", "GeneratedOn"),          # word report generated
    "FQD": ("FQNumber", "FQnumber"),                # form deleted from queue
    "ANR": ("EntName", "DateANR"),                  # annual return generated
    "ADN": ("Name", "RefType"),                     # master file created
    "CIN": ("IncorpDate", "EntType", "IncorpPlace"),  # entity incorporated
    "BNN": ("BusName", "BusRegNr", "DateRegistration"),  # business registration
    "GACN": ("Address", "City", "Country"),         # address card created
    "OFA": ("OfficerTitle", "DateAppoint"),         # officer appointed
    "OFF": ("OfficerTitle", "DateAppoint"),         # first director/secretary
    "OFD": ("OfficerTitle", "DateResign"),          # officer resigned
    "OFP": ("OfficerTitle", "DateEffective"),       # officer particulars changed
    "SMP": ("OfficerText", "ShareClass", "DateEffective"),  # shareholder particulars
    "SHA": ("ShareClass", "NrShare"),               # shares issued
    "SHZ": ("ShareClass", "NrShare", "TransDescr"), # share transaction deleted
    "IDRN": ("IdType", "Description", "IdCode"),    # identity record added
}

# On a creation event everything is "new", so a field-by-field diff is noise --
# a master file being created reported its address-card numbers and not the name
# of the thing created. Say what was created instead.
_ACTION_ONLY = {
    "ADN", "SFMG", "SWRG", "ANR", "FQD", "GACN", "BNN", "CIN",
    "OFA", "OFF", "OFD", "SHA", "SHZ", "IDRN",
}

# Viewpoint master-file status codes (its own RECS lookup). A status trail
# reading "0 -> 8" is not a status trail.
STATUS_CODES = {
    "0": "Open/Active",
    "8": "Closed/Inactive",
    "9": "Marked for Removal",
}


def status_change(old: str | None, new: str | None) -> list[dict]:
    """RefStatus rows carry only a pair of status codes — decode them."""
    if not old and not new:
        return []
    return [{
        "field": "Status",
        "label": "Status",
        "old": STATUS_CODES.get(old or "", old) or None,
        "new": STATUS_CODES.get(new or "", new) or None,
    }]

# Viewpoint stores each statutory register as its own address-card pointer, so
# filing them all at one address writes ~17 near-identical changes. That is one
# decision, not seventeen.
_ADDRESS_CARD = re.compile(r"^AdNr(?P<type>..)$")
_STATUTORY_PREFIX = "S"
_COLLAPSE_THRESHOLD = 3


def is_noise(field: str) -> bool:
    """True for Viewpoint's internal flags — never show these to a user."""
    return field in _NOISE_EXACT or bool(_NOISE_PATTERN.search(field))


def extract_changes(
    parsed: dict,
    labels: dict[str, str] | None = None,
    addresses: dict[str, str] | None = None,
) -> list[dict]:
    """EventString key/value map -> [{field, label, old, new}], changes only.

    Reads both conventions. A pipe whose halves are equal (Confidential=False|False)
    is context that happened to be written in change form — not a change.

    `addresses` maps a Viewpoint address-card number to its text. Viewpoint records
    an address change as a change of card number, so without it the trail reads
    "Business Address: 6030 -> 8029", which tells the reader nothing.
    """
    labels = labels or {}
    changes: dict[str, tuple[str, str]] = {}

    for key, value in parsed.items():
        value = value or ""
        if key.startswith(("Old", "New")):
            field = key[3:]
            if not field or is_noise(field):
                continue
            old, new = changes.get(field, ("", ""))
            if key.startswith("Old"):
                changes[field] = (value, new)
            else:
                changes[field] = (old, value)
        elif "|" in value:
            if is_noise(key) or key in _KEYS:
                continue
            new, _, old = value.partition("|")
            if new != old:
                changes.setdefault(key, (old, new))

    return _collapse_statutory_registers([
        {
            "field": f,
            "label": labels.get(f, f),
            "old": _resolve(f, old, addresses),
            "new": _resolve(f, new, addresses),
        }
        for f, (old, new) in sorted(changes.items())
        if old != new
    ])


def _resolve(field: str, value: str, addresses: dict[str, str] | None) -> str | None:
    """Turn an address-card number into the address it points at."""
    if not value:
        return None
    if addresses and _ADDRESS_CARD.match(field):
        return addresses.get(value, value)
    return value


def _collapse_statutory_registers(changes: list[dict]) -> list[dict]:
    """Fold "all 17 statutory registers moved to card 1" into a single change."""
    def is_statutory(c):
        m = _ADDRESS_CARD.match(c["field"])
        return bool(m) and m.group("type").startswith(_STATUTORY_PREFIX)

    statutory = [c for c in changes if is_statutory(c)]
    if len(statutory) < _COLLAPSE_THRESHOLD:
        return changes

    moves = {(c["old"], c["new"]) for c in statutory}
    if len(moves) != 1:                       # went to different places — keep detail
        return changes

    old, new = moves.pop()
    rest = [c for c in changes if not is_statutory(c)]
    return [{
        "field": "statutory_registers",
        "label": f"Statutory registers ({len(statutory)})",
        "old": old,
        "new": new,
    }] + rest


def summarize(event_code: str | None, parsed: dict, labels: dict[str, str] | None = None) -> list[dict]:
    """For events that record an action, not an edit: say WHAT the action was.

    "Form generated" is useless; "Form: NAR1 - Annual Return Private Company" is
    the answer to the question the user is actually asking.
    """
    labels = labels or {}
    fields = _SUMMARY_FIELDS.get(event_code or "", ())
    return [
        {
            "field": f,
            "label": labels.get(f, f),
            "old": None,
            "new": parsed[f],
        }
        for f in fields
        if parsed.get(f)
    ]


def describe(
    event_code: str | None,
    parsed: dict,
    labels: dict[str, str] | None = None,
    addresses: dict[str, str] | None = None,
) -> list[dict]:
    """The full "what changed" for one event.

    For an action (a form generated, a file created) the action is the answer.
    Otherwise it's the real changes, falling back to the action fields when a
    blob turns out to hold no diff at all."""
    if event_code in _ACTION_ONLY:
        return summarize(event_code, parsed, labels) or extract_changes(parsed, labels, addresses)
    return (extract_changes(parsed, labels, addresses)
            or summarize(event_code, parsed, labels))


def render(changes: list[dict], side: str) -> str | None:
    """Flatten to the audit_log.old_value / new_value text column, for search.

    One change renders bare ("2025-07-21"); several are prefixed with their field
    so the two columns stay readable side by side.
    """
    if not changes:
        return None
    vals = [(c["label"], c.get(side)) for c in changes]
    present = [(lbl, v) for lbl, v in vals if v]
    if not present:
        return None
    if len(changes) == 1:
        return present[0][1]
    return "; ".join(f"{lbl}: {v}" for lbl, v in present)
