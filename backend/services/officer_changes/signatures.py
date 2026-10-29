"""A director's drawn signature on an ND2A / ND2B (e-signature-nd2, Levi 2026-10-29).

A director opens the Confirm & File link, draws a signature and presses the
button. This module is everything the portal does with that picture: decide who
is asked for one (`must_sign`), check what arrives (`decode`), keep it (`store`)
and hand it back to the renderers (`images_for`).

WHAT IT IS NOT. The picture is for the PORTAL'S OWN COPIES of the form and the
written resolution. It is never sent to CR (TPSI e-filing carries no image),
never put in an audit row, and has no delete path. It lives in a service-role-only
table (migration 059) and is read back only by `images_for`.

THE POST IS UNAUTHENTICATED, so `decode` trusts nothing: a data URL of a PNG, at
most 200 KB, at most 1600 x 600, and with real ink on it. Size is checked before
the bytes are opened, and the dimensions before the pixels are decoded, so a
small file that declares a vast canvas costs nothing.

`must_sign` and `images_for` NEVER RAISE. The first is asked while rendering a
page a client is looking at, and a database fault there must give the page it
has always given, not a 500; the second is asked from inside renderers whose
callers are not prepared for it to fail.
"""
from __future__ import annotations

import base64
import binascii
import io
import sys

from PIL import Image, ImageChops

from db.supabase import get_supabase
from services import nar1_approvals
from services.officer_changes import cases, resolution

_TABLE = "officer_change_signatures"

#: Decoded bytes. A pad canvas of 600 x 200 is a few KB; this is generous.
MAX_BYTES = 200 * 1024
MAX_WIDTH = 1600
MAX_HEIGHT = 600
#: Pixels that are neither transparent nor white. A signature is thousands; a
#: speck of dust or a stray click is a handful.
MIN_INK_PIXELS = 200

_PREFIX = "data:image/png;base64,"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class SignatureError(ValueError):
    """The submitted signature cannot be used. The message is for the log, not
    the client: the page says one fixed sentence whatever the reason."""


def _ink(img: Image.Image) -> int:
    """How many pixels are visible and not white.

    A pad draws dark strokes on a transparent canvas; one that paints its own
    white background must count the same. So ink is "alpha above zero AND any
    colour channel below 250".
    """
    rgba = img.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    visible = alpha.point(lambda a: 255 if a > 0 else 0)
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    not_white = darkest.point(lambda v: 255 if v < 250 else 0)
    return ImageChops.multiply(visible, not_white).histogram()[255]


def decode(data_url) -> bytes:
    """The PNG bytes behind a `data:image/png;base64,` URL, or `SignatureError`."""
    if not isinstance(data_url, str) or not data_url.startswith(_PREFIX):
        raise SignatureError("not a PNG data URL")
    encoded = data_url[len(_PREFIX):]
    # Bound the work BEFORE decoding: base64 inflates by a third.
    if len(encoded) > (MAX_BYTES * 4) // 3 + 8:
        raise SignatureError("signature too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("not base64") from exc
    if len(raw) > MAX_BYTES:
        raise SignatureError("signature too large")
    if not raw.startswith(_PNG_MAGIC):
        raise SignatureError("not a PNG")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "PNG":
                raise SignatureError("not a PNG")
            width, height = img.size
            if not (0 < width <= MAX_WIDTH and 0 < height <= MAX_HEIGHT):
                raise SignatureError("wrong dimensions")
            img.load()
            if _ink(img) < MIN_INK_PIXELS:
                raise SignatureError("nothing drawn")
    except SignatureError:
        raise
    except Exception as exc:  # noqa: BLE001 — truncated, corrupt or bomb: all the same refusal
        raise SignatureError("unreadable image") from exc
    return raw


# -- who is asked ------------------------------------------------------------------

def _is_current_director(sb, entity_id: str, person_id: str) -> bool:
    rows = (sb.table("entity_officers").select("id").eq("entity_id", entity_id)
            .eq("is_current", True).eq("role", "director").eq("person_id", person_id)
            .execute().data) or []
    return bool(rows)


def _signs_resolution(entity_id: str, entries: list[dict], person_id: str) -> bool:
    """Is this person on the written resolution's signature lines?

    Asked of `resolution.signatory_people`, the sibling of the function that
    draws those lines, so there is one rule for who signs and the pad can never
    be offered to someone the resolution has no line for. The officers it reads
    are the pickers' own list (`cases._current_officers`), named and carrying
    their person ids."""
    officers = cases._current_officers(entity_id, entries)
    return person_id in {pid for _name, pid in resolution.signatory_people(entries, officers)}


def must_sign(case: dict, person_id) -> bool:
    """Is this person a director with a box to sign on this form?

    Only a director with somewhere for the signature to print is ever asked, so
    no picture is collected that appears nowhere (technical review B6, B7):

      * ND2A — an INCOMING director (their consent), or a director on the
        board after the changes (the resolution's line), or the form's
        signatory when that natural person is a director (the page-3 box).
      * ND2B — only the form's signatory by person id, when a director.

    False on any doubt or error: the page is then exactly today's.
    """
    try:
        if not person_id:
            return False
        sb = get_supabase()
        entity_id = case["entity_id"]
        if (cases.signatory_person_id(entity_id) == person_id
                and _is_current_director(sb, entity_id, person_id)):
            return True
        if case.get("form_code") != "Nd2a":
            return False
        entries = cases.list_entries(case["id"])
        if any(e.get("kind") == "appointment" and e.get("capacity") == "director"
               and e.get("person_id") == person_id for e in entries):
            return True
        return _signs_resolution(entity_id, entries, person_id)
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        print(f"[signatures] must_sign failed: {exc}", file=sys.stderr)
        return False


def required_signers_strict(case: dict) -> list[dict]:
    """`required_signers` without the safety net: a fault RAISES.

    The wrapper below turns every fault into `[]`, which cannot tell "nobody has
    a box" from "could not read". Most callers want that (a page must render),
    but one must not: the report that says "the board has changed since this was
    sent" compares the live set with the frozen one, and a passing read error
    would otherwise tell the operator to Restart verification -- which throws
    away every collected signature. That caller uses this and treats a raise as
    "unknown".
    """
    sb = get_supabase()
    entity_id = case["entity_id"]
    roles_by_person: dict[str, list[str]] = {}

    def add(person_id, role: str) -> None:
        if person_id:
            roles = roles_by_person.setdefault(person_id, [])
            if role not in roles:
                roles.append(role)

    sig_name, _corporate, sig_person = cases._signatory_row(entity_id)
    if sig_person and _is_current_director(sb, entity_id, sig_person):
        add(sig_person, "form")

    officer_names: dict[str, str] = {}
    line_names: dict[str, str] = {}
    if case.get("form_code") == "Nd2a":
        entries = cases.list_entries(case["id"])
        for entry in entries:
            if entry.get("kind") == "appointment" and entry.get("capacity") == "director":
                add(entry.get("person_id"), "consent")
        officers = cases._current_officers(entity_id, entries)
        officer_names = {o.get("person_id"): o.get("name") for o in officers
                         if o.get("person_id")}
        for line_name, person_id in resolution.signatory_people(entries, officers):
            add(person_id, "resolution")
            if person_id:
                line_names[person_id] = line_name

    people = cases._by_id("persons", list(roles_by_person), "id,full_name")
    return [{"person_id": pid,
             # The officers list first (spec 2.2), then the person's own record.
             "name": (officer_names.get(pid)
                      or (people.get(pid) or {}).get("full_name")
                      or (sig_name if pid == sig_person else "")
                      or line_names.get(pid) or ""),
             "roles": roles}
            for pid, roles in roles_by_person.items()]


def required_signers(case: dict) -> list[dict]:
    """Everyone `must_sign` would say yes to, as `[{"person_id", "name", "roles"}]`
    (nd2-multi-signer, Levi 2026-10-29).

    `must_sign` answers for one person; the multi-signer mode needs the whole
    list at once -- one panel per director, and the set a round converges on.
    The rules and their ORDER are the ones above: the form's signatory when a
    director (`form`), then the incoming ND2A directors (`consent`), then the
    resolution's signature lines that carry a person (`resolution`). Someone
    under more than one rule is listed once with every role.

    A body-corporate director has no person id, so never appears: nobody can
    draw on this page for it, which is already true of `must_sign`.
    `tests/officer_changes/test_required_signers.py` runs both over the same
    fixtures and fails if they ever disagree about a person -- the two are
    separate code, and that test is the only thing joining them.

    NEVER RAISES. A fault gives `[]` and a stderr line, like `must_sign`, which
    gives False: the screen then reports "no director has a box to sign" rather
    than a 500. (An empty list is therefore ambiguous between "nobody" and "could
    not read"; `required_signers_strict` is the variant that is not, and no caller
    may FREEZE the result of this one without checking it is not empty.)
    """
    try:
        return required_signers_strict(case)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[signatures] required_signers failed: {exc}", file=sys.stderr)
        return []


# -- keeping and reading -----------------------------------------------------------

def store(*, case_id: str, approval_id: str, person_id: str, revision: int,
          png: bytes) -> dict:
    """Insert one signature. Returns the row WITHOUT the picture, so nothing a
    caller does with the result (an audit row, a log line) can carry it."""
    rows = (get_supabase().table(_TABLE).insert({
        "case_id": case_id, "approval_id": approval_id, "person_id": person_id,
        "revision": revision, "image_b64": base64.b64encode(png).decode("ascii"),
    }).execute().data) or []
    if not rows:
        raise RuntimeError("signature insert returned no row")
    return {k: v for k, v in rows[0].items() if k != "image_b64"}


def images_for(case: dict) -> dict[str, bytes]:
    """`person_id -> PNG bytes` for the case's CURRENT verification revision,
    and only once the client has approved; `{}` otherwise or on any error.

    The revision lock is what makes a re-send supersede older signatures: a
    director who signed Rev. 1 has not signed the Rev. 2 form.
    """
    try:
        if case.get("client_approved") is not True:
            return {}
        rows = (get_supabase().table(_TABLE).select("person_id,image_b64")
                .eq("case_id", case["id"])
                .eq("revision", nar1_approvals.current_revision(case))
                .execute().data) or []
        out: dict[str, bytes] = {}
        for row in rows:
            try:
                out[row["person_id"]] = base64.b64decode(row["image_b64"], validate=True)
            except (binascii.Error, ValueError, KeyError, TypeError):
                continue
        return out
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        print(f"[signatures] images_for failed: {exc}", file=sys.stderr)
        return {}
