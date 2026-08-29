"""Which deployment this is — the single reading of APP_ENV.

Several interlocks in this codebase hang off "is this production": whether mail
may reach a real client, whether the header says TEST, whether a filing spends
real money. They must all agree, and before this module they were separate
`os.environ.get("APP_ENV")` reads that could drift apart one edit at a time.

AN UNSET APP_ENV IS NOT PRODUCTION. That direction is the safe one and it is
chosen deliberately: an unconfigured deployment gets the test-environment
guards, and the cost of being wrong is a suppressed email rather than a
statutory form sent to a real client from a machine nobody meant to be live.
"""
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def is_production() -> bool:
    """True only when APP_ENV is exactly 'prod' (case- and space-insensitive).

    Cached: a deployment does not change environment mid-life, and a value that
    could flip between two reads inside one request would make every interlock
    built on it racy. Tests call `is_production.cache_clear()`.
    """
    return (os.environ.get("APP_ENV") or "").strip().lower() == "prod"
