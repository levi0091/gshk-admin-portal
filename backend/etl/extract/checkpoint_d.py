"""PBI-40 Block 3 — Checkpoint D extract (Viewpoint → dict rows, read-only).

Restores the RefMaster corporate-party superset the first migration split away:
non-client corporate master records + the linkage that marks which RefCodes act
as a corporate party.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine

# Non-client corporates = RefMaster RefType='C' with NO Entity (client) row.
# Name resolves from RefMaster.Name (CompName is 0% filled for this population —
# see docs/pbi40-block0-gap-audit.md).
NONCLIENT_CORPORATES_QUERY = text("""
    SELECT rm.RefCode, rm.Name, rm.CompName, rm.SearchName, rm.ChnsName
    FROM RefMaster rm
    WHERE rm.RefType = 'C'
      AND rm.RefCode NOT IN (SELECT EntCode FROM Entity)
""")


def extract_nonclient_corporates(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(NONCLIENT_CORPORATES_QUERY)]


# Address history for the non-client corporates only (client addresses were
# already handled by Checkpoint C). The caller picks the current one per RefCode.
NONCLIENT_CORPORATE_ADDRESSES_QUERY = text("""
    SELECT ra.RefCode, ra.AddrNr, ra.AddrType, ra.Effective, ra.Cancelled
    FROM RefAddress ra
    WHERE ra.RefCode IN (SELECT RefCode FROM RefMaster WHERE RefType = 'C')
      AND ra.RefCode NOT IN (SELECT EntCode FROM Entity)
""")


def extract_nonclient_corporate_addresses(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(NONCLIENT_CORPORATE_ADDRESSES_QUERY)]


# Every RefType='C' RefCode that acts as a corporate party anywhere (director/
# secretary via Officers.AddrCode, controller via EntityOwners.RefCode, or
# shareholder via Share_Transactions.AddrCode). These entities get
# is_corporate_party=true. Covers both client entities and the backfilled
# non-clients that are actually referenced (the §9 authoritative population).
CORPORATE_PARTY_REFCODES_QUERY = text("""
    SELECT DISTINCT rm.RefCode
    FROM RefMaster rm
    WHERE rm.RefType = 'C'
      AND ( rm.RefCode IN (SELECT AddrCode FROM Officers)
         OR rm.RefCode IN (SELECT RefCode  FROM EntityOwners)
         OR rm.RefCode IN (SELECT AddrCode FROM Share_Transactions) )
""")


def extract_corporate_party_refcodes(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return [r.RefCode for r in conn.execute(CORPORATE_PARTY_REFCODES_QUERY)]
