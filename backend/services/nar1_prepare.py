"""Building one NAR1's XML from the company record — the one owner.

EXTRACTED FROM `routers/tpsi.prepare_filing` (2026-09-17) because it acquired a
second caller. Client Verification is now the FIRST stage (migration 046), so
`routers/cases.send_verification` has to be able to produce the return before CR
has ever seen it — the client approves `request_xml`, not `validated_xml`.

A second hand-written copy of this would be free to drift, and the way anyone
would find out is a client approving a document built from different rules than
the one filed: a different signing capacity, a different signatory, a different
default. The two callers differ in how they report a failure and in nothing
else, so the HTTP mapping stays in the routers and the domain exceptions come
out of here untranslated:

  LookupError                 the entity id is wrong
  LoaderFailed                the profile store could not be read
  nar1_mapper.MappingError    the company record cannot produce a NAR1
  anything else               operational — the credential store, mostly

`build_form_xml` MAKES NO WRITES and opens no filing row. Opening one is the
caller's decision: `prepare_filing` rebuilds or creates, `send_verification`
does the same but only once it knows the return renders.
"""
from datetime import datetime, timedelta, timezone

from services import nar1_cases
from services.tpsi import credentials
from services.tpsi.forms import nar1, nar1_mapper, nar1_source
from services.tpsi.forms.cr_vocabularies import default_capacity


class LoaderFailed(Exception):
    """`nar1_source.load_entity_graph` failed on transport, not on data.

    Its own type because the two callers both have to tell it apart from
    everything else: the loader has an observed, un-eliminated failure mode
    against Supabase's edge (`httpx.RemoteProtocolError: Server disconnected`,
    a Cloudflare 400), and that must reach an operator as an upstream failure
    they can retry deliberately rather than as a 500 reading like a bug in the
    mapper. Before the extraction this distinction was a `try` around one call
    in `routers/tpsi`; folding it into "anything else" lost it, and a test
    caught that.

    `.cause` is the original, because the message names the exception type.
    """

    def __init__(self, entity_id: str, cause: Exception):
        super().__init__(str(cause))
        self.entity_id = entity_id
        self.cause = cause


def hk_year() -> int:
    """The current year in Hong Kong.

    Not UTC: Railway and Supabase both run UTC, and a return prepared at 02:00
    in the office on 1 January is 18:00 on 31 December there — which would
    prepare last year's annual return.
    """
    return (datetime.now(timezone.utc) + timedelta(hours=8)).year


def resolve_capacity(graph: dict, nar1_case_id: str | None) -> str | None:
    """selectCapacityDesc: the operator's choice, else CR's usual arrangement.

    It cannot be derived from the company profile — it depends on who at GSHK
    signs — so it is stored on the case by PATCH /cases/{id} and read from
    there rather than accepted as a request field: the value filed must be the
    one the operator saw on screen and the audit trail recorded.

    The fallback (Levi 2026-08-31) is the arrangement every real GSHK client
    has — GSHK Ltd is the secretary and a GSHK director signs for it — rather
    than making the operator answer the same question on every case. An
    INDIVIDUAL signatory defaults to "Director" (Levi 2026-09-14), from CR's
    Individual vocabulary; CR keeps two, and a "(Body Corporate)" capacity on a
    natural person is a misstatement.
    """
    capacity = None
    if nar1_case_id:
        try:
            capacity = (nar1_cases.get_case(nar1_case_id)
                        or {}).get("signatory_capacity")
        except LookupError:
            # A bad case id is the /cases endpoints' error to raise, not this
            # one's; preparing must not 404 on a field it merely consults.
            capacity = None
    if capacity:
        return capacity

    try:
        resolved = nar1_mapper._derive_signatory(graph)
    except Exception:  # noqa: BLE001 — a graph too thin to resolve is the
        resolved = None  # mapper's problem to report, not this line's.
    if not resolved:
        return None
    return default_capacity(is_corporate=resolved.get("is_corporate") is True)


async def build_form_xml(*, entity_id: str, nar1_case_id: str | None,
                         user_id: str, year: int | None = None,
                         signatory: dict | None = None) -> str:
    """CR's formModel for this entity's annual return, as a bare fragment.

    `user_id` supplies the SIGNING IDENTITY — who signs for the body corporate.
    A GSHK client's secretary is a company and CR will not take a company as a
    signatory: it wants the human acting for it, named in associatedPersonId /
    associatedPersonName. It is read from the caller's own CR credential rather
    than accepted as a field, so the value filed is one this user actually
    holds rather than one the caller could assert.

    AT CLIENT VERIFICATION THAT IS THE SENDER, WHO NEED NOT BE THE SIGNER. That
    is fine and is why it is not pinned: Data Verification rebuilds the draft
    before validating (`filings.REBUILDABLE_STAGES`), so the identity that
    reaches CR is the one belonging to whoever actually prepares the filing.
    `services/nar1_verification.approval_divergence` ignores these fields for
    the same reason — a different GSHK signer is not a change to the client's
    particulars.
    """
    try:
        graph = await nar1_source.load_entity_graph(entity_id)
    except LookupError:
        raise                       # "no entity <id>" — the caller's id is wrong
    except Exception as exc:
        raise LoaderFailed(entity_id, exc) from exc
    capacity = resolve_capacity(graph, nar1_case_id)
    signing_identity = credentials.load_signatory_identity(user_id)
    data = nar1_mapper.map_entity(
        graph,
        year=year or hk_year(),
        # Passed straight through: an explicit override replaces the whole
        # signer, capacity included.
        signatory=signatory,
        signatory_capacity=capacity,
        signing_identity=signing_identity,
    )
    return nar1.build_nar1_xml(data)
