"""A document is gated by the module of the record it belongs to.

THERE IS NO `documents` MODULE (Levi 2026-09-07). It was one of six, with its
own read/write/delete, and being separate meant it could disagree with the
record it describes in both directions:

  * a role granted Companies (edit) could not upload the certificate of
    incorporation for a company it was trusted to edit the CR number of;
  * a role with `documents:delete` and no `companies` grant at all could remove
    a company's papers without ever being able to open the company.

Neither is a distinction anybody wanted to make. The right to read a record is
the right to read the papers filed against it, and the right to change the
record is the right to add and remove them. So:

    company-owned  (a certificate, an AoA)          -> companies
    person-owned   (an id scan, a proof of address) -> persons
    case-owned     (a CR receipt, a wet-signed NAR1)-> nar1

which is the SAME mapping migration 037 already applied to the audit trail's
`module` column, for the same reason and after the same complaint. This module
is the permission half of that decision.

WHY THE OWNER MUST BE READ FIRST. The routes in `routers/documents.py` are keyed
by document id alone — nothing in the URL says whose document it is — so the
guard cannot be a static `require_permission(...)` and has to load the row
before it can name the module. That is one extra Supabase round trip on a
download, which is the price of asking the right question; the alternative was a
module that answered the wrong one.

It FAILS CLOSED. A document whose owner cannot be resolved is refused rather
than waved through on the reasoning that it "probably" belongs to a company:
these routes hand out signed URLs to identity scans and delete filed papers.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from db.supabase import get_supabase

# THE MODULE, NOT ITS NAMES. `from middleware.auth import _resolve_user` binds
# the original function here at import time, so `patch("middleware.auth.
# _resolve_user")` — which every test in this repo uses to sign a request in —
# rebinds the attribute over there and this module keeps calling the real one,
# which then reaches for live Supabase credentials. That is the same
# green-local/red-CI shape the repo has already been bitten by; going through
# the module means there is one resolver and one place to patch it.
from middleware import auth

#: The owner column actually populated on a `documents` row -> the module that
#: owner belongs to. The keys mirror `document_service._OWNER_COLUMN`; kept as
#: its own map rather than imported so a new owner kind has to be given a module
#: deliberately instead of inheriting one by accident.
MODULE_FOR_OWNER_COLUMN = {
    "entity_id": "companies",
    "person_id": "persons",
    "nar1_case_id": "nar1",
}

#: Read in this order, so a row carrying more than one owner column resolves the
#: same way every time. `document_service._owner_kind_of` walks its map in the
#: same order; a case-owned receipt also carries no entity_id, so in practice
#: exactly one is ever set.
_OWNER_COLUMNS = ("entity_id", "person_id", "nar1_case_id")

#: `documents:delete` has no equivalent under an owner module — neither
#: `companies` nor `persons` has a delete level, and inventing one would mean a
#: migration seeding a permission nobody had asked for. Removing a document is
#: therefore a WRITE on the owning record, which is what it is: changing what
#: the record holds.
_LEVEL = {"read": "read", "write": "write", "delete": "write"}


def module_for_document(document_id: str) -> str:
    """Which permission module governs this document. Raises 404 if unknown.

    A 404 rather than a 403 for a missing document, because that is what the
    route would have answered anyway once it tried to read it — and a 403 here
    would tell an unauthorised caller that the id exists.
    """
    row = (
        get_supabase().table("documents")
        .select("entity_id,person_id,nar1_case_id")
        .eq("id", document_id).limit(1).execute().data or []
    )
    if not row:
        raise HTTPException(404, "Document not found")

    for column in _OWNER_COLUMNS:
        if row[0].get(column):
            return MODULE_FOR_OWNER_COLUMN[column]

    # Fails closed. A document with no owner at all cannot be attributed to a
    # module, and these routes sign URLs for identity scans.
    raise HTTPException(
        403, "this document is not filed against a company, a person or a "
             "case, so there is no record whose permissions could allow it")


def require_document_permission(permission: str):
    """`require_permission`, for a route that only knows the document id.

    Mirrors `middleware.auth.require_permission` step for step — the same
    password-change interlock in the same place (BEFORE the super_admin bypass,
    spec §7), the same bypass, the same 403 text — so the two cannot drift into
    answering differently for the same user.
    """
    level = _LEVEL[permission]

    async def check(
        document_id: str,
        credentials: HTTPAuthorizationCredentials = Depends(auth.security),
    ) -> dict:
        user = auth._resolve_user(credentials.credentials)
        auth._refuse_until_password_changed(user)

        # BEFORE the owner is read, exactly as the bypass sits before the
        # permission check in `require_permission`. A super admin passes on
        # every module, so loading the row to find out which one would be a
        # Supabase round trip whose answer cannot change the outcome.
        if user["role_name"] == "super_admin":
            return user

        module = module_for_document(document_id)
        if level not in auth._permissions_for(user, module):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return check
