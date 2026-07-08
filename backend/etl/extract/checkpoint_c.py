from sqlalchemy import text
from sqlalchemy.engine import Engine

CONTACTS_QUERY = text("""
    SELECT RefCode, SeqNr, cType, cText, Preferred
    FROM RefContacts
""")


def extract_contacts(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(CONTACTS_QUERY)
        return [dict(row._mapping) for row in result]


CHARGES_QUERY = text("""
    SELECT EntCode, ChargeNr, ChargeRef, ChargeType, MortgageeAddrCode,
           MortgageeDescr, DateRegistration, DateDischarge, PropertyDescr, Currency
    FROM Charges
""")


def extract_charges(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(CHARGES_QUERY)
        return [dict(row._mapping) for row in result]


TASKS_QUERY = text("""
    SELECT t.RefCode, t.SeqNr, t.ToDoCode, t.DueDate, t.Remark, t.IsDone, tc.Description
    FROM ToDoList t
    LEFT JOIN ToDoCodes tc ON t.ToDoCode = tc.ToDoCode
""")


def extract_tasks(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(TASKS_QUERY)
        return [dict(row._mapping) for row in result]


ADDRESS_ASSIGNMENTS_QUERY = text("""
    SELECT RefCode, SeqNr, AddrType, AddrNr, Effective, Cancelled
    FROM RefAddress
""")


def extract_address_assignments(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(ADDRESS_ASSIGNMENTS_QUERY)
        return [dict(row._mapping) for row in result]


FORM_FILINGS_QUERY = text("""
    SELECT FQnumber, EntCode, FormCode, DateGenerate, DateSigned, DateFiled,
           DateFileDeadLine, FiledROC, FieldDetails
    FROM FormQue
""")


def extract_form_filings(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(FORM_FILINGS_QUERY)
        return [dict(row._mapping) for row in result]


EVENT_LOG_QUERY = text("""
    SELECT EventNr, EventClass, KeyCode, DateEvent, EventCode, Ucode,
           Description, EventString, RecordID
    FROM EventLog
""")


def extract_event_log(engine: Engine) -> list[dict]:
    """ALL EventLog rows import — including ShowInLog=0 — per Levi's
    explicit decision, so no WHERE clause filters on that column."""
    with engine.connect() as conn:
        result = conn.execute(EVENT_LOG_QUERY)
        return [dict(row._mapping) for row in result]


REF_STATUS_QUERY = text("""
    SELECT RefCode, SeqNr, SType, OldStat, NewStat, DateChange, Ucode, CDescr
    FROM RefStatus
""")


def extract_ref_status(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(REF_STATUS_QUERY)
        return [dict(row._mapping) for row in result]


VP_USERS_QUERY = text("""
    SELECT Ucode, Uname
    FROM VpUser
""")


def extract_vp_users(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        result = conn.execute(VP_USERS_QUERY)
        return {row.Ucode: row.Uname for row in result}


EVENTS_FORM_QUERY = text("""
    SELECT EventNr, FQNumber
    FROM EventsForm
""")


def extract_events_form(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(EVENTS_FORM_QUERY)
        return [dict(row._mapping) for row in result]
