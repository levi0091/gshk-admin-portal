from sqlalchemy import text
from sqlalchemy.engine import Engine

ADDRESSES_QUERY = text("""
    SELECT AddrNr, Address, Address2, Address3, Address4, Address5,
           City, State, Country, PostalCode,
           AddressLoc1, AddressLoc2, CityLoc
    FROM Addresses
""")


def extract_addresses(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(ADDRESSES_QUERY)
        return [dict(row._mapping) for row in result]


PERSONS_QUERY = text("""
    SELECT rm.RefCode, rm.Name, rm.ChnsName, rm.SearchName, rm.DateEntered,
           c.GivenNames, c.FormerName, c.FormerGivenNames, c.Aliases,
           c.ChnsFormerName, c.ChnsAliases,
           c.Email, c.BirthDate, c.Gender, c.Nationality, c.NationalityCode,
           c.Occupation, c.PlaceBirth, c.MaritalStatus, c.DateDeath
    FROM RefMaster rm
    LEFT JOIN Compliance c ON rm.RefCode = c.AddrCode
    WHERE rm.RefType = 'I'
""")


def extract_persons(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(PERSONS_QUERY)
        return [dict(row._mapping) for row in result]


ENTITIES_QUERY = text("""
    SELECT e.EntCode, rm.CompName, rm.Name, rm.DateEntered, e.IncorpNr, e.IncorpDate,
           e.IncorpPlace, e.Status, e.DateLastAnRe, e.DateNextAnRe,
           e.DateDueAnRe, e.DateNextAGM, e.MA_DirMin, e.MA_DirMax,
           e.MA_AgmWaived, e.PrevEntName, e.DateNameChanged, e.Note,
           e.AccountNote
    FROM Entity e
    JOIN RefMaster rm ON e.EntCode = rm.RefCode
""")

PRINCIPAL_BUS_NAMES_QUERY = text("""
    SELECT EntCode, BusRegNr, ChineseBusName, DateCessation, DateRegistration
    FROM BusNames
    WHERE PrincipleBNR = 1
""")


def extract_entities(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(ENTITIES_QUERY)
        return [dict(row._mapping) for row in result]


def extract_principal_business_names(engine: Engine) -> dict[str, dict]:
    """One principal BusNames row per EntCode. If an EntCode has more than one
    PrincipleBNR=1 row (2 known cases in the live data), the most recently
    registered wins and the tie is left for the reconciliation error log."""
    with engine.connect() as conn:
        result = conn.execute(PRINCIPAL_BUS_NAMES_QUERY)
        rows = [dict(r._mapping) for r in result]

    by_entity: dict[str, dict] = {}
    ties: set[str] = set()
    for row in rows:
        code = row["EntCode"]
        existing = by_entity.get(code)
        if existing is None:
            by_entity[code] = row
        else:
            ties.add(code)
            if (row.get("DateRegistration") or "") > (existing.get("DateRegistration") or ""):
                by_entity[code] = row
    by_entity["_ties"] = ties  # inspected by the loader to log to reconciliation
    return by_entity


IDENTITY_DOCUMENTS_QUERY = text("""
    SELECT ir.RefCode, ir.SeqNr, ir.IdType, ir.IdCode, ir.Country,
           ir.FromDate, ir.ToDate
    FROM IdentityRegister ir
    JOIN RefMaster rm ON ir.RefCode = rm.RefCode
    WHERE rm.RefType = 'I'
""")


def extract_identity_documents(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(IDENTITY_DOCUMENTS_QUERY)
        return [dict(row._mapping) for row in result]


COMPLIANCE_IDENTITY_DOCUMENTS_QUERY = text("""
    SELECT c.AddrCode, c.PassportNr, c.PasPlaceIssue, c.PasDateIssue,
           c.PasDateExpire, c.IDcardNr, c.IDcardDateIssue
    FROM Compliance c
    JOIN RefMaster rm ON c.AddrCode = rm.RefCode
    WHERE rm.RefType = 'I'
      AND (c.PassportNr IS NOT NULL OR c.IDcardNr IS NOT NULL)
""")


def extract_compliance_identity_documents(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(COMPLIANCE_IDENTITY_DOCUMENTS_QUERY)
        return [dict(row._mapping) for row in result]


OFFICERS_QUERY = text("""
    SELECT EntCode, SeqNr, AddrCode, OfficerType, Position,
           DateAppoint, DateResign, ReasonResign
    FROM Officers
""")


def extract_officers(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(OFFICERS_QUERY)
        return [dict(row._mapping) for row in result]


BENEFICIAL_OWNERS_QUERY = text("""
    SELECT EntCode, SeqNr, RefCode, EntOwnCountry,
           PercInterest, PercVote, DateFrom, DateTo
    FROM EntityOwners
""")


def extract_beneficial_owners(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(BENEFICIAL_OWNERS_QUERY)
        return [dict(row._mapping) for row in result]
