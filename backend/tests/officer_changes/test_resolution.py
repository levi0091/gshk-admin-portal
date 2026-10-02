"""The written resolution an ND2A goes with (Jacqueline A3)."""
import pymupdf

from services.officer_changes import resolution

CASE = {"id": "K1", "case_no": "ND2A-2026-0007", "form_code": "Nd2a"}
ENTITY = {"company_name": "Sample Trading Limited", "br_number": "12345678"}
OFFICERS = [
    {"officer_id": "O1", "role": "director", "name": "CHAN Tai Man"},
    {"officer_id": "O2", "role": "director", "name": "WONG Mei Ling"},
    {"officer_id": "O3", "role": "company_secretary", "name": "Get Started HK Limited"},
]
CEASE_WONG = {"id": "N1", "kind": "cessation", "capacity": "director", "officer_id": "O2",
              "cessation_reason": "R", "effective_date": "2026-09-12",
              "party": {"name": "WONG Mei Ling"}}
APPOINT_LEE = {"id": "N2", "kind": "appointment", "capacity": "director",
               "effective_date": "2026-09-12", "party": {"name": "LEE Ka Ho"}}


def text(pdf: bytes) -> str:
    return " ".join(" ".join(p.get_text().split()) for p in pymupdf.open(stream=pdf))


def test_resolution_lists_each_change_and_the_filing_authority():
    out = text(resolution.render(CASE, ENTITY, [CEASE_WONG, APPOINT_LEE], OFFICERS))
    assert "WRITTEN RESOLUTIONS OF THE DIRECTORS" in out
    assert "SAMPLE TRADING LIMITED" in out and "12345678" in out
    assert "THAT the resignation of WONG Mei Ling as a director of the Company with " \
           "effect from 12 September 2026 be and is hereby accepted." in out
    assert "THAT LEE Ka Ho, having consented to act, be and is hereby appointed as a " \
           "director of the Company with effect from 12 September 2026." in out
    assert "Form ND2A to the Companies Registry" in out
    assert "ND2A-2026-0007" in out


def test_signatories_are_directors_in_office_excluding_the_deceased():
    dead = {**CEASE_WONG, "cessation_reason": "D"}
    out = text(resolution.render(CASE, ENTITY, [dead], OFFICERS))
    assert "by reason of death" in out
    signatures = out.split("Signed by the directors")[1]
    assert "CHAN Tai Man" in signatures and "WONG Mei Ling" not in signatures
    assert "Get Started HK Limited" not in signatures


def test_with_no_director_in_office_the_incoming_directors_sign():
    out = text(resolution.render(CASE, ENTITY, [APPOINT_LEE],
                                 [o for o in OFFICERS if o["role"] != "director"]))
    assert "LEE Ka Ho" in out.split("Signed by the directors")[1]


def test_an_undated_change_reads_the_date_of_these_resolutions():
    out = text(resolution.render(CASE, ENTITY, [{**APPOINT_LEE, "effective_date": None}],
                                 OFFICERS))
    assert "with effect from the date of these resolutions" in out


def test_a_secretary_change_is_worded_for_a_secretary():
    sec = {"id": "N3", "kind": "appointment", "capacity": "company_secretary",
           "effective_date": "2026-09-12", "party": {"name": "New Sec Limited"}}
    assert "appointed as the company secretary of the Company" in text(
        resolution.render(CASE, ENTITY, [sec], OFFICERS))


def test_file_name():
    assert resolution.file_name(CASE) == "Written-Resolution-ND2A-2026-0007.pdf"
