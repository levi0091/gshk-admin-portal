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


ENTITY_NAME_CHANGES_QUERY = text("""
    SELECT EntCode, SeqNr, OldName, OldChnsName, NewName, NewChnsName,
           DateApplied, DateConfirmed
    FROM EntNameChanges
""")


def extract_entity_name_changes(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(ENTITY_NAME_CHANGES_QUERY)
        return [dict(row._mapping) for row in result]


SHARE_TRANSACTIONS_QUERY = text("""
    SELECT EntCode, IssueNr, ShareClass, AddrCode, TransType, TransDate,
           NrShare, BalanceShare, IssuePrice, Paid, CertificateNr, Posted
    FROM Share_Transactions
""")


def extract_share_transactions(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(SHARE_TRANSACTIONS_QUERY)
        return [dict(row._mapping) for row in result]


SHARE_CERTIFICATES_QUERY = text("""
    SELECT SeqNr, EntCode, AddrCode, ShareClass, IssueDate, CertificateNr,
           NrShare, CancelDate
    FROM Share_Certificates
""")


def extract_share_certificates(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(SHARE_CERTIFICATES_QUERY)
        return [dict(row._mapping) for row in result]
