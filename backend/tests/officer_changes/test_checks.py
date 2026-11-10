"""Manual checks at Data Verification (Jacqueline A4, p. 25's mock-up)."""
from services.officer_changes import checks

ND2A = {"id": "K1", "form_code": "Nd2a"}
ND2B = {"id": "K2", "form_code": "Nd2b"}


def appoint(eid, name, capacity="director", kyc=False, party_type="individual"):
    return {"id": eid, "kind": "appointment", "capacity": capacity, "kyc_cleared": kyc,
            "party_type": party_type, "party": {"name": name}}


def cease(eid, name, reason="R"):
    return {"id": eid, "kind": "cessation", "capacity": "director",
            "cessation_reason": reason, "party": {"name": name}}


def doc(entry_id, type_, name="f.pdf", when="2026-09-15T00:00:00Z"):
    return {"id": f"D-{entry_id}-{type_}", "entry_id": entry_id, "document_type_code": type_,
            "file_name": name, "uploaded_at": when}


def by_code(items, code):
    return [i for i in items if i["code"] == code]


def test_kyc_per_appointment():
    items = checks.manual_checks(ND2A, [appoint("N1", "LEE Ka Ho", kyc=True),
                                        appoint("N2", "HO New")], [], route="esign")
    kyc = by_code(items, "kyc")
    assert [(i["label"], i["ok"], i["kind"]) for i in kyc] == [
        ("KYC / WorldCheck cleared — LEE Ka Ho", True, "tick"),
        ("KYC / WorldCheck cleared — HO New", False, "tick")]


def test_a_cessation_raises_no_check_and_a_resignation_letter_is_never_one():
    """Levi 2026-10-29 (ND2 change request 5): the resignation-letter check is
    gone, so a leaver -- by resignation or by death -- adds nothing to the list
    and a letter on file or off it changes nothing."""
    entries = [cease("N1", "WONG Mei Ling"), cease("N2", "LATE Person", reason="D")]
    for docs in ([], [doc("N1", "resignation_letter", "resignation.pdf")]):
        assert checks.manual_checks(ND2A, entries, docs, route="manual") == []


def test_checks_are_kyc_only():
    """Levi 2026-10-05: the written resolution goes to the client WITH the
    ND2A, and CR's consent signature is the consent -- neither is a check.
    Levi 2026-10-29: nor is a resignation letter."""
    entries = [cease("N1", "WONG Mei Ling"), appoint("N2", "LEE Ka Ho")]
    for route in ("esign", "manual"):
        items = checks.manual_checks(ND2A, entries, [], route=route)
        assert [i["code"] for i in items] == ["kyc"], route
        assert not by_code(items, "resignation_letter")


def test_nd2b_has_no_checks():
    entries = [{"id": "N1", "kind": "change", "party": {"name": "CHAN"}}]
    assert checks.manual_checks(ND2B, entries, [], route="manual") == []


def test_incomplete_names_what_is_left():
    items = checks.manual_checks(ND2A, [appoint("N1", "LEE Ka Ho"),
                                        appoint("N2", "HO New", kyc=True)], [],
                                 route="manual")
    assert checks.incomplete(items) == ["KYC / WorldCheck cleared — LEE Ka Ho"]


def test_a_cessation_alone_leaves_nothing_incomplete():
    """It no longer blocks leaving Data Verification."""
    items = checks.manual_checks(ND2A, [cease("N1", "WONG Mei Ling")], [], route="manual")
    assert checks.incomplete(items) == []
