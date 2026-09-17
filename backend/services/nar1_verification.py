"""Has the return moved since the client approved it?

WHY THIS EXISTS. Client Verification is the FIRST stage (migration 046), so the
client approves `request_xml` — the return built from the company record — and
CR has not seen it yet. When CR then rejects it at Data Verification, the
operator fixes the record and re-validates, and the approval STANDS (Levi
2026-09-17: the client is mailed by hand if the correction warrants it). That is
a deliberate trade, and it has a consequence nobody should have to remember:
the return that gets filed can differ from the one a director said yes to.

So the bytes that were mailed are kept (`nar1_cases.verification_xml`) and this
module answers, in the operator's terms, which fields have moved since. It
WARNS AND NEVER REFUSES. The thing that refuses is the pre-submit drift gate,
which asks a different question — does the snapshot still match the live
company record — and is untouched by any of this.

NOT A HASH. A hash can say that something changed; the case screen has to say
WHAT changed, because the operator's next decision is whether it is worth
re-mailing a director over. `drift.compare` already produces exactly that shape
and is reused rather than reimplemented.

WHAT IS IGNORED, AND WHY EACH ONE. `drift.flatten` already drops the presenter
block and `signatoryDate`. Three more are dropped here and nowhere else:

  associatedPersonId / associatedPersonName
        WHO AT GSHK SIGNS FOR THE BODY CORPORATE. Read from the preparing
        user's own CR credential, so it changes whenever a different colleague
        picks the case up at Data Verification — which is the normal case, not
        the exception, now that the sender and the signer are two different
        steps. It is not a particular of the client's company and a director
        would not recognise it as a change to their return.
  selectPersonId
        The same fact for a natural-person signatory.

Everything else is reported. A director's address, a share class, the company
name, the registered office — those are what the client approved.
"""
import re

from services.tpsi import drift

#: `flatten` indexes a repeat as `indDir[2]`, so the last path step is not
#: always a bare element name. Stripped before the ignore test — these three
#: are singletons today and the pattern must not depend on that staying true.
_INDEX = re.compile(r"\[\d+\]$")

#: See the module docstring. GSHK's own signing identity, which moves for
#: reasons that have nothing to do with the client's particulars.
IGNORED_LEAVES = frozenset({
    "associatedPersonId", "associatedPersonName", "selectPersonId",
})


def approval_divergence(case: dict, filing: dict | None) -> list:
    """Fields that differ between what was mailed and what would be filed.

    Empty when nothing has moved, when no verification has been sent, or when
    the case predates `verification_xml` — an absent snapshot is "we cannot
    say", and the screen must not turn that into "nothing changed". The caller
    distinguishes the two by whether `verification_sent_at` is set.
    """
    mailed = (case or {}).get("verification_xml")
    current = (filing or {}).get("request_xml")
    if not mailed or not current:
        return []
    return [
        d for d in drift.compare(mailed, current)
        if _INDEX.sub("", d["path"].rsplit("/", 1)[-1]) not in IGNORED_LEAVES
    ]
