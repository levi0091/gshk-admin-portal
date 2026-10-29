"""What a rendering after confirmation prints as signatures (e-signature-nd2).

`signatures.images_for(case)` answers "who drew what" as `person_id -> PNG`. The
renderers need more than that, because neither form carries a person id: the ND2A
renderer finds a consent box by the NAMES printed in it, and the page-3 box by the
typed signatory's name. This module is the one place that turns the first into the
second, so the four callers that render a confirmed form (the admin preview, the
receipt, the filed copy and the manual route's download) cannot each do it a
little differently.

  * a consent signature is an INCOMING DIRECTOR's, keyed by `english_name(person)`
    exactly as `nd2a_mapper` prints it;
  * the form-level signature is the form's signatory's, and only when that
    signatory is a natural person (`cases.signatory_person_id`; for a body
    corporate secretary, which is nearly every GSHK client, it is None and the box
    stays blank).

`for_form` NEVER RAISES and returns None when there is nothing to print: its
callers sit in front of a download and in the middle of an email, and a database
fault must give them today's unsigned copy, not a failure.
"""
from __future__ import annotations

import sys

from services.officer_change_form import stamp
from services.officer_changes import cases, nd2a_mapper, signatures


def for_form(case: dict) -> stamp.Signatures | None:
    """The `signatures=` argument for `officer_change_form.render`, or None."""
    try:
        images = signatures.images_for(case)
        if not images:
            return None
        out = stamp.Signatures()
        if case.get("form_code") == "Nd2a":
            # EVERY incoming director, signed or not: the same-name guard has to
            # see the one who did not sign, or a signer's image would match that
            # person's box too and print there.
            incoming = [e["person_id"] for e in cases.list_entries(case["id"])
                        if e.get("kind") == "appointment" and e.get("capacity") == "director"
                        and e.get("person_id")]
            seen: dict = {}
            for person_id, person in cases._by_id("persons", incoming).items():
                key = stamp.Signatures.key(*nd2a_mapper.english_name(person))
                # Two directors who print as the same name cannot be told apart
                # by it, so neither is printed rather than one in the other's box.
                seen[key] = None if key in seen else images.get(person_id)
            out.consents = {k: v for k, v in seen.items() if v}
        name, is_corporate, person_id = cases._signatory_row(case["entity_id"])
        if person_id and not is_corporate and person_id in images:
            out.signatory = (name, images[person_id])
        return out if out else None
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        print(f"[signed_copies] no signatures printed: {exc}", file=sys.stderr)
        return None
