"""services/nar1_verification.py — has the return moved since approval?

THE QUESTION THIS ANSWERS EXISTS BECAUSE OF A TRADE. Client Verification is the
first stage (migration 046), so the client approves a return CR has not seen.
When CR then rejects it, the operator fixes the record and re-validates and the
approval STANDS (Levi 2026-09-17). That is deliberate — and it means the return
filed can differ from the one a director said yes to, which somebody has to be
able to see without diffing a nine-page form by eye.

Pure in, pure out: no Supabase, no CR.
"""
from services import nar1_verification as nv


def _return(*, company="TEST COMPANY LIMITED", building="Test Tower",
            signer="T260727100116D", extra=""):
    """A NAR1 fragment in CR's own shape — a bare fragment with undeclared
    `cr:` prefixes, as `tpsi_filings.request_xml` stores it."""
    return f"""
    <cr:submission><cr:EForm><cr:formModel>
      <cr:brNo>T0001137</cr:brNo>
      <cr:compNameE>{company}</cr:compNameE>
      <cr:roAddr>
        <cr:flatFlrBlk>Flat A</cr:flatFlrBlk>
        <cr:bldg>{building}</cr:bldg>
        <cr:ctryRegion>HKG</cr:ctryRegion>
      </cr:roAddr>
      <cr:associatedPersonId>{signer}</cr:associatedPersonId>
      <cr:associatedPersonName>DIRECTOR, ONE</cr:associatedPersonName>
      {extra}
    </cr:formModel></cr:EForm></cr:submission>"""


def test_an_untouched_return_reports_nothing():
    case = {"verification_xml": _return()}
    assert nv.approval_divergence(case, {"request_xml": _return()}) == []


def test_a_changed_particular_is_reported_with_both_values():
    case = {"verification_xml": _return(building="Test Tower")}
    diffs = nv.approval_divergence(case, {"request_xml": _return(building="New Tower")})

    assert len(diffs) == 1
    assert diffs[0]["validated"] == "Test Tower"
    assert diffs[0]["current"] == "New Tower"
    # A label a human can act on, not a raw XPath.
    assert "Building" in diffs[0]["field"]


def test_a_different_gshk_signer_is_NOT_a_change_to_the_clients_return():
    """THE COMMON CASE, not the exception. associatedPersonId comes from the
    preparing user's own CR credential, and the sender and the validator are
    two different steps now — so a colleague picking the case up at Data
    Verification rewrites it every time. Reporting that as "the return changed
    since the client approved" would cry wolf on every case and teach an
    operator to ignore the notice that matters."""
    case = {"verification_xml": _return(signer="T260727100116D")}
    diffs = nv.approval_divergence(case, {"request_xml": _return(signer="T999999999999Z")})
    assert diffs == []


def test_the_signatory_date_is_not_a_change_either():
    """`drift.flatten` already drops it: it is `_hk_today()` at build time and
    changes every day by construction."""
    case = {"verification_xml": _return(
        extra="<cr:signatoryDate>01/09/2026</cr:signatoryDate>")}
    current = {"request_xml": _return(
        extra="<cr:signatoryDate>17/09/2026</cr:signatoryDate>")}
    assert nv.approval_divergence(case, current) == []


def test_a_real_change_still_surfaces_alongside_an_ignored_one():
    """The ignore list must not swallow the whole comparison."""
    case = {"verification_xml": _return(company="OLD NAME LIMITED",
                                        signer="T260727100116D")}
    current = {"request_xml": _return(company="NEW NAME LIMITED",
                                      signer="T999999999999Z")}
    diffs = nv.approval_divergence(case, current)
    assert [d["current"] for d in diffs] == ["NEW NAME LIMITED"]


def test_no_snapshot_is_an_empty_list_and_the_caller_tells_them_apart():
    """A case sent before migration 046 has no stored snapshot. "We cannot say"
    and "nothing changed" are different answers and both come back as [] here —
    which is why `composite` also reports `approval_snapshot_kept`."""
    assert nv.approval_divergence({}, {"request_xml": _return()}) == []
    assert nv.approval_divergence({"verification_xml": _return()}, None) == []
    assert nv.approval_divergence(None, None) == []


def test_a_director_added_after_approval_is_reported():
    """Not merely an edited value — a field that exists on one side only. The
    client approved a two-director board and a three-director board would be
    filed."""
    case = {"verification_xml": _return()}
    current = {"request_xml": _return(
        extra="<cr:indDirList><cr:indDir><cr:indvEngSname>LEE"
              "</cr:indvEngSname></cr:indDir></cr:indDirList>")}
    diffs = nv.approval_divergence(case, current)
    assert len(diffs) == 1
    assert diffs[0]["validated"] is None      # absent, not empty
    assert diffs[0]["current"] == "LEE"
