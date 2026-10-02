"""A client officer's stored e-Registry account (spec §5, B-9).

The password goes in encrypted and comes out only through `load_for_signing`.
Nothing else — metadata, errors, the stored row — may carry it or a hint of it.
"""
import pytest

from services.officer_changes import eservice
from tests.officer_changes.fakes import FakeSupabase

SECRET = "Correct-Horse-9"


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({"person_eservice_credentials": []})
    monkeypatch.setattr(eservice, "get_supabase", lambda: fake)
    monkeypatch.setattr(eservice, "encrypt", lambda p: "enc:" + p[::-1])
    monkeypatch.setattr(eservice, "decrypt", lambda c: c[len("enc:"):][::-1])
    return fake


def test_nothing_stored_reads_as_not_configured(db):
    assert eservice.metadata("P1") == {
        "configured": False, "eservice_user_id": None,
        "eservice_person_name": None, "has_password": False, "updated_at": None,
    }
    assert eservice.load_for_signing("P1") is None


def test_save_encrypts_and_metadata_never_carries_the_password(db):
    meta = eservice.save("P1", eservice_user_id=" ER123456 ",
                         eservice_person_name="CHAN Tai Man",
                         password=SECRET, user_id="U1")
    assert meta["configured"] is True and meta["has_password"] is True
    assert meta["eservice_user_id"] == "ER123456"
    assert SECRET not in str(meta) and SECRET[-4:] not in str(meta)
    row = db.rows("person_eservice_credentials")[0]
    assert row["person_id"] == "P1" and row["updated_by"] == "U1"
    assert SECRET not in str(row)
    assert eservice.load_for_signing("P1") == ("ER123456", "CHAN Tai Man", SECRET)


def test_save_without_a_password_keeps_the_stored_one(db):
    eservice.save("P1", eservice_user_id="ER1", eservice_person_name="A",
                  password=SECRET, user_id="U1")
    eservice.save("P1", eservice_user_id="ER2", eservice_person_name="B", user_id="U1")
    assert eservice.load_for_signing("P1") == ("ER2", "B", SECRET)
    assert len(db.rows("person_eservice_credentials")) == 1


def test_a_first_save_needs_a_password(db):
    with pytest.raises(ValueError, match="password"):
        eservice.save("P1", eservice_user_id="ER1", eservice_person_name="A",
                      user_id="U1")
    assert db.rows("person_eservice_credentials") == []


@pytest.mark.parametrize("user_id, password", [("  ", SECRET), ("ER1", "")])
def test_blank_user_id_or_blank_password_is_refused(db, user_id, password):
    with pytest.raises(ValueError) as caught:
        eservice.save("P1", eservice_user_id=user_id, eservice_person_name="A",
                      password=password, user_id="U1")
    assert SECRET not in str(caught.value)


def test_incomplete_credentials_cannot_sign(db):
    db.tables["person_eservice_credentials"].append(
        {"person_id": "P1", "eservice_user_id": "ER1",
         "eservice_person_name": None, "eservice_password_enc": "enc:x"})
    assert eservice.load_for_signing("P1") is None
    assert eservice.metadata("P1")["configured"] is True


def test_metadata_for_answers_every_id(db):
    eservice.save("P1", eservice_user_id="ER1", eservice_person_name="A",
                  password=SECRET, user_id="U1")
    out = eservice.metadata_for(["P1", "P2"])
    assert out["P1"]["has_password"] is True
    assert out["P2"]["configured"] is False
    assert SECRET not in str(out)
    assert eservice.metadata_for([]) == {}


def test_clear_removes_the_row(db):
    eservice.save("P1", eservice_user_id="ER1", eservice_person_name="A",
                  password=SECRET, user_id="U1")
    assert eservice.clear("P1") is True
    assert eservice.clear("P1") is False
    assert eservice.metadata("P1")["configured"] is False
