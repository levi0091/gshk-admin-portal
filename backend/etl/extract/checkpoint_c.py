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
