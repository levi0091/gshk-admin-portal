"""A director's drawn signature on the ND2 Confirm & File page (e-signature-nd2,
Levi 2026-10-29): `services/officer_changes/signatures.py`.

Spec section 6, tests 1 and 2, plus the lookup `images_for` that the printing
ticket consumes. The page and POST behaviour is held in test_public_approval.py.
"""
import base64
import io
import os

import pytest
from PIL import Image, ImageDraw

from services import nar1_approvals
from services.officer_changes import cases, signatures
from tests.officer_changes.fakes import FakeSupabase


# -- a signature, drawn the way the pad draws it ----------------------------------

def _png_bytes(size=(600, 200), ink=True, background=(0, 0, 0, 0), mode="RGBA") -> bytes:
    """What `canvas.toDataURL('image/png')` produces: a transparent canvas with
    dark strokes on it."""
    img = Image.new("RGBA", size, background)
    if ink:
        draw = ImageDraw.Draw(img)
        draw.line([(20, 150), (120, 40), (200, 160), (320, 60)], fill=(0, 0, 0, 255), width=6)
    if mode != "RGBA":
        img = img.convert(mode)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _url(raw: bytes, prefix="data:image/png;base64,") -> str:
    return prefix + base64.b64encode(raw).decode()


# -- 1. decode ---------------------------------------------------------------------

def test_a_drawn_signature_is_accepted_and_returned_as_png_bytes():
    raw = _png_bytes()
    assert signatures.decode(_url(raw)) == raw


@pytest.mark.parametrize("bad", [
    None, "", 42, "not a data url",
    "data:image/jpeg;base64,/9j/4AAQ",
    "data:text/html;base64,PGgxPg==",
    "image/png;base64,AAAA",
])
def test_a_value_that_is_not_a_png_data_url_is_refused(bad):
    with pytest.raises(signatures.SignatureError):
        signatures.decode(bad)


def test_bytes_that_are_not_a_png_are_refused():
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(b"<html>not a picture</html>"))


def test_undecodable_base64_is_refused():
    with pytest.raises(signatures.SignatureError):
        signatures.decode("data:image/png;base64,@@@@")


def test_a_png_signature_header_with_a_broken_body_is_refused():
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(b"\x89PNG\r\n\x1a\n" + b"garbage" * 20))


def test_a_jpeg_dressed_up_as_a_png_url_is_refused():
    buf = io.BytesIO()
    Image.new("RGB", (100, 50), "black").save(buf, format="JPEG")
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(buf.getvalue()))


def test_more_than_200_kb_is_refused_before_it_is_opened(monkeypatch):
    opened = []
    real = Image.open
    monkeypatch.setattr(Image, "open", lambda *a, **k: opened.append(1) or real(*a, **k))
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (200 * 1024)
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(big))
    assert not opened


def test_a_valid_png_over_the_cap_is_refused():
    # Incompressible noise, so the encoded PNG is well over 200 KB.
    img = Image.frombytes("RGBA", (400, 150), os.urandom(400 * 150 * 4))
    out = io.BytesIO()
    img.save(out, format="PNG")
    raw = out.getvalue()
    assert len(raw) > 200 * 1024
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(raw))


@pytest.mark.parametrize("size", [(1601, 200), (600, 601), (5000, 5000)])
def test_oversize_dimensions_are_refused(size):
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(_png_bytes(size=size)))


def test_the_largest_allowed_canvas_is_accepted():
    assert signatures.decode(_url(_png_bytes(size=(1600, 600))))


def test_a_blank_transparent_canvas_has_no_ink():
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(_png_bytes(ink=False)))


def test_a_white_filled_canvas_has_no_ink():
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(_png_bytes(ink=False, background=(255, 255, 255, 255))))


def test_a_few_stray_pixels_are_not_a_signature():
    img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    for x in range(10):
        img.putpixel((x, 5), (0, 0, 0, 255))
    out = io.BytesIO()
    img.save(out, format="PNG")
    with pytest.raises(signatures.SignatureError):
        signatures.decode(_url(out.getvalue()))


def test_ink_on_an_opaque_white_background_counts():
    """A pad that paints its background white still carries a signature."""
    img = Image.new("RGBA", (600, 200), (255, 255, 255, 255))
    ImageDraw.Draw(img).line([(10, 10), (300, 150)], fill=(10, 10, 80, 255), width=8)
    out = io.BytesIO()
    img.save(out, format="PNG")
    assert signatures.decode(_url(out.getvalue())) == out.getvalue()


def test_a_palette_png_is_read_without_error():
    # Not every PNG is RGBA; the ink count must not assume a mode.
    raw = _png_bytes(mode="P")
    assert signatures.decode(_url(raw)) == raw


# -- 2. who must sign --------------------------------------------------------------

def _tables():
    return {
        "persons": [{"id": pid, "full_name": pid} for pid in ("P1", "P2", "P3", "P9", "PS")],
        "entities": [{"id": "GSHK", "company_name": "Get Started HK Limited"},
                     {"id": "E1", "company_name": "Kanenas Holding Limited"}],
        "entity_officers": [
            {"id": "O1", "entity_id": "E1", "person_id": "P1", "role": "director",
             "party_type": "individual", "is_current": True},
            {"id": "O2", "entity_id": "E1", "person_id": "P2", "role": "director",
             "party_type": "individual", "is_current": True},
            {"id": "OX", "entity_id": "E1", "person_id": "P9", "role": "director",
             "party_type": "individual", "is_current": False},
            {"id": "O3", "entity_id": "E1", "corporate_entity_id": "GSHK",
             "role": "company_secretary", "party_type": "corporate", "is_current": True},
        ],
        "company_secretaries": [],
        "officer_change_entries": [],
        "officer_change_signatures": [],
        "nar1_client_approvals": [],
    }


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(_tables())
    monkeypatch.setattr(cases, "get_supabase", lambda: fake)
    monkeypatch.setattr(signatures, "get_supabase", lambda: fake)
    monkeypatch.setattr(nar1_approvals, "get_supabase", lambda: fake)
    return fake


def _case(form="Nd2a", **over):
    return {"id": "C1", "entity_id": "E1", "form_code": form, **over}


def _entry(db, kind, **cols):
    db.tables["officer_change_entries"].append(
        {"id": f"N{len(db.tables['officer_change_entries'])}", "case_id": "C1",
         "kind": kind, **cols})


def test_an_incoming_director_signs_their_consent(db):
    _entry(db, "appointment", capacity="director", person_id="P3",
           party_type="individual")
    assert signatures.must_sign(_case(), "P3") is True


def test_an_incoming_secretary_does_not_sign(db):
    _entry(db, "appointment", capacity="company_secretary", person_id="P3",
           party_type="individual")
    assert signatures.must_sign(_case(), "P3") is False


def test_a_director_who_stays_signs_the_resolution(db):
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    assert signatures.must_sign(_case(), "P1") is True


def test_a_director_who_is_leaving_has_no_box_and_no_pad(db):
    """Review B6: the written resolution is signed by the board AFTER the changes,
    so a pad for the leaver would collect a signature that prints nowhere."""
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    assert signatures.must_sign(_case(), "P2") is False


def test_when_every_director_leaves_the_board_before_signs(db):
    """Mirrors `resolution.signatories`: with nobody left it falls back to the
    directors in office before, so those people do have a line to sign."""
    _entry(db, "cessation", officer_id="O1", person_id="P1", party_type="individual")
    _entry(db, "cessation", officer_id="O2", person_id="P2", party_type="individual")
    assert signatures.must_sign(_case(), "P1") is True


def test_a_former_director_unknown_person_and_none_do_not_sign(db):
    assert signatures.must_sign(_case(), "P9") is False   # is_current false
    assert signatures.must_sign(_case(), "NOBODY") is False
    assert signatures.must_sign(_case(), None) is False
    assert signatures.must_sign(_case(), "") is False


def test_a_secretary_only_does_not_sign(db):
    db.tables["entity_officers"].append(
        {"id": "O5", "entity_id": "E1", "person_id": "PS", "role": "company_secretary",
         "party_type": "individual", "is_current": True})
    assert signatures.must_sign(_case(), "PS") is False


def test_the_forms_signatory_signs_when_a_director(db):
    """A natural-person secretary who is also a director signs page 3."""
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P1", "secretary_name": None})
    assert signatures.must_sign(_case("Nd2b"), "P1") is True
    assert signatures.must_sign(_case("Nd2a"), "P1") is True


def test_an_nd2b_asks_nobody_when_the_signatory_is_a_company(db):
    # GSHK Ltd is the secretary (O3): the usual case, so no pad on an ND2B,
    # even for a current director who has a change on it.
    _entry(db, "change", officer_id="O1", person_id="P1", party_type="individual")
    assert signatures.must_sign(_case("Nd2b"), "P1") is False


def test_an_nd2b_does_not_use_nd2a_rules(db):
    _entry(db, "appointment", capacity="director", person_id="P3")
    assert signatures.must_sign(_case("Nd2b"), "P3") is False


def test_must_sign_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("database is down")
    monkeypatch.setattr(cases, "get_supabase", boom)
    monkeypatch.setattr(signatures, "get_supabase", boom)
    assert signatures.must_sign(_case(), "P1") is False


def test_signatory_person_id_follows_the_register_first_order(db):
    assert cases.signatory_person_id("E1") is None   # GSHK Ltd, a body corporate
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": False, "is_current": True,
         "person_id": "P1", "secretary_name": None})
    assert cases.signatory_person_id("E1") == "P1"


def test_a_corporate_register_row_ahead_of_a_person_officer_means_no_person(db):
    db.tables["company_secretaries"].append(
        {"id": "S1", "entity_id": "E1", "is_gshk": True, "is_current": True,
         "person_id": None, "secretary_name": "Get Started HK Limited"})
    db.tables["entity_officers"].append(
        {"id": "O5", "entity_id": "E1", "person_id": "PS", "role": "company_secretary",
         "party_type": "individual", "is_current": True})
    assert cases.signatory_person_id("E1") is None


# -- store / images_for ------------------------------------------------------------

def test_store_writes_the_image_as_base64_text(db):
    raw = _png_bytes()
    row = signatures.store(case_id="C1", approval_id="A1", person_id="P1",
                           revision=2, png=raw)
    saved = db.tables["officer_change_signatures"][0]
    assert saved["image_b64"] == base64.b64encode(raw).decode()
    assert (saved["case_id"], saved["approval_id"], saved["person_id"],
            saved["revision"]) == ("C1", "A1", "P1", 2)
    assert row["id"] == saved["id"]
    assert "image_b64" not in row   # the picture is never handed back to a caller


def _signed(db, *, revision=1, person="P1", approval="A1", raw=None):
    raw = raw or _png_bytes()
    db.tables["officer_change_signatures"].append({
        "id": f"S-{approval}", "case_id": "C1", "approval_id": approval,
        "person_id": person, "revision": revision,
        "image_b64": base64.b64encode(raw).decode()})
    return raw


def test_images_for_returns_person_to_png_for_the_current_revision(db):
    raw = _signed(db, revision=2)
    case = _case(client_approved=True, verification_revision=2)
    assert signatures.images_for(case) == {"P1": raw}


def test_images_for_is_empty_until_the_case_is_approved(db):
    _signed(db, revision=2)
    assert signatures.images_for(_case(client_approved=None, verification_revision=2)) == {}
    assert signatures.images_for(_case(client_approved=False, verification_revision=2)) == {}


def test_images_for_ignores_an_older_revisions_signature(db):
    _signed(db, revision=1)
    assert signatures.images_for(_case(client_approved=True, verification_revision=2)) == {}


def test_images_for_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(signatures, "get_supabase", boom)
    assert signatures.images_for(_case(client_approved=True, verification_revision=1)) == {}


def test_images_for_skips_a_row_it_cannot_decode(db):
    db.tables["officer_change_signatures"].append({
        "id": "S1", "case_id": "C1", "approval_id": "A1", "person_id": "P1",
        "revision": 1, "image_b64": "@@not base64@@"})
    assert signatures.images_for(_case(client_approved=True, verification_revision=1)) == {}
