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
