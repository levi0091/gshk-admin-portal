from sqlalchemy import text
from sqlalchemy.engine import Engine

SHARE_CAPITAL_QUERY = text("""
    SELECT EntCode, ShareClass, ShareClassName, Currency,
           NomValShare, VotesPerShare, Issued, PaidCap
    FROM Share_Capital
""")


def extract_share_capital(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(SHARE_CAPITAL_QUERY)
        return [dict(row._mapping) for row in result]


BUSINESS_NAMES_QUERY = text("""
    SELECT EntCode, SeqNr, BusRegNr, BusName, ChineseBusName,
           DateRegistration, DateRenew, DateCessation, Status
    FROM BusNames
""")


def extract_business_names(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(BUSINESS_NAMES_QUERY)
        return [dict(row._mapping) for row in result]
