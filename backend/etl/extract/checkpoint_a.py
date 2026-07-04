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
    SELECT rm.RefCode, rm.Name, rm.ChnsName, rm.SearchName,
           c.GivenNames, c.FormerName, c.FormerGivenNames, c.Aliases,
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
