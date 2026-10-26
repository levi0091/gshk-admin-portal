"""An in-memory stand-in for the PostgREST query builder, for the submit tests.

Why a fake store and not MagicMock chains: the defect these tests pin down is
a STATE MACHINE problem — a timeout left a filing in a stage from which the
ordinary validate -> sign -> submit chain could run again. A MagicMock answers
every query with whatever it was told to, so it cannot show a row moving from
one stage to the next and being refused on the second pass. This keeps real
rows, applies real filters, and returns the rows an UPDATE changed, exactly as
PostgREST does, so a conditional UPDATE that matches nothing really does come
back empty.

Only the builder methods the code under test calls are implemented. An
unimplemented one raises AttributeError, which is the right failure: a test
that silently answered a query it did not understand would pass for the wrong
reason.
"""
import copy
import threading
import uuid
from types import SimpleNamespace


class UniqueViolation(Exception):
    """What postgrest-py raises for a 23505, near enough for the code under
    test: it reads the code and the index name off the message."""

    def __init__(self, index: str):
        self.code = "23505"
        super().__init__(
            f"{{'code': '23505', 'message': 'duplicate key value violates "
            f"unique constraint \"{index}\"'}}"
        )


#: Migration 056's case-level lock, restated so the fake refuses what Postgres
#: would. Kept beside the store rather than inside a test so every test that
#: writes through the store is held to it.
CASE_LOCK_INDEX = "uq_tpsi_filings_case_locked"
CASE_LOCK_STAGES = ("submitting", "submission_unknown", "submitted", "registered")


class FakeStore:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables: dict[str, list[dict]] = {
            name: [dict(r) for r in rows] for name, rows in (tables or {}).items()
        }
        # One statement at a time, as Postgres applies them: a conditional
        # UPDATE is atomic there, and the concurrency test depends on it being
        # atomic here.
        self.lock = threading.Lock()

    def table(self, name: str) -> "_Query":
        return _Query(self, name)

    def rows(self, name: str) -> list[dict]:
        return self.tables.setdefault(name, [])

    def get(self, name: str, row_id: str) -> dict:
        return next(r for r in self.rows(name) if r.get("id") == row_id)

    def _check(self, name: str) -> None:
        if name != "tpsi_filings":
            return
        held: dict = {}
        for row in self.rows(name):
            if row.get("stage") in CASE_LOCK_STAGES and row.get("nar1_case_id"):
                if row["nar1_case_id"] in held:
                    raise UniqueViolation(CASE_LOCK_INDEX)
                held[row["nar1_case_id"]] = row["id"]


class _Query:
    def __init__(self, store: FakeStore, name: str):
        self.store = store
        self.name = name
        self.mode = "select"
        self.payload = None
        self.filters = []
        self._negate = False
        self._order = None
        self._limit = None
        self._single = False

    # ---- verbs -----------------------------------------------------------
    def select(self, *_a, **_k):
        self.mode = "select"
        return self

    def update(self, payload: dict):
        self.mode, self.payload = "update", dict(payload)
        return self

    def insert(self, payload: dict):
        self.mode, self.payload = "insert", dict(payload)
        return self

    # ---- filters ---------------------------------------------------------
    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, test):
        negate, self._negate = self._negate, False
        self.filters.append((lambda r: not test(r)) if negate else test)
        return self

    def eq(self, col, value):
        return self._add(lambda r: r.get(col) == value)

    def neq(self, col, value):
        return self._add(lambda r: r.get(col) != value)

    def in_(self, col, values):
        values = list(values)
        return self._add(lambda r: r.get(col) in values)

    def is_(self, col, value):
        want_null = value in (None, "null")
        return self._add(lambda r: (r.get(col) is None) == want_null)

    def lt(self, col, value):
        return self._add(lambda r: r.get(col) is not None and r.get(col) < value)

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    # ---- execution -------------------------------------------------------
    def _matching(self) -> list[dict]:
        return [r for r in self.store.rows(self.name)
                if all(f(r) for f in self.filters)]

    def execute(self):
        with self.store.lock:
            return self._execute()

    def _execute(self):
        if self.mode == "insert":
            row = {"id": str(uuid.uuid4()), **self.payload}
            self.store.rows(self.name).append(row)
            try:
                self.store._check(self.name)
            except UniqueViolation:
                self.store.rows(self.name).remove(row)
                raise
            return SimpleNamespace(data=[copy.deepcopy(row)], count=1)

        if self.mode == "update":
            hits = self._matching()
            before = [copy.deepcopy(r) for r in hits]
            for row in hits:
                row.update(self.payload)
            try:
                self.store._check(self.name)
            except UniqueViolation:
                for row, old in zip(hits, before):
                    row.clear()
                    row.update(old)
                raise
            return SimpleNamespace(data=[copy.deepcopy(r) for r in hits],
                                   count=len(hits))

        rows = self._matching()
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        rows = [copy.deepcopy(r) for r in rows]
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None, count=len(rows))
        return SimpleNamespace(data=rows, count=len(rows))
