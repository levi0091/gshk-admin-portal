"""An in-memory stand-in for the PostgREST client, for officer-change tests.

Supports the subset of the builder the officer-change services use: select,
eq/neq/in_/is_/gte/lte, order, limit, insert, update, upsert, delete, execute,
and rpc for `next_case_no`. Rows are plain dicts; ids are generated when a row
arrives without one. It is deliberately small — a test that needs a filter it
does not support should fail loudly rather than be answered wrongly.
"""
from __future__ import annotations

import copy
import itertools
import re
from types import SimpleNamespace

_ids = itertools.count(1)


def new_id(prefix: str = "id") -> str:
    return f"{prefix}-{next(_ids)}"


class _Query:
    def __init__(self, db: "FakeSupabase", table: str):
        self._db = db
        self._table = table
        self._filters = []
        self._op = "select"
        self._payload = None
        self._order = None
        self._limit = None
        self._on_conflict = None

    # -- builders -------------------------------------------------------------
    def select(self, *_cols, **_kw):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None, **_kw):
        self._op, self._payload, self._on_conflict = "upsert", payload, on_conflict
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, value):
        self._filters.append(lambda r: r.get(col) == value)
        return self

    def neq(self, col, value):
        self._filters.append(lambda r: r.get(col) != value)
        return self

    def in_(self, col, values):
        values = list(values)
        self._filters.append(lambda r: r.get(col) in values)
        return self

    def ilike(self, col, pattern):
        """SQL ILIKE: `%` any run, `_` one character, `\\` escapes either."""
        out, chars = [], iter(str(pattern))
        for ch in chars:
            if ch == "\\":
                out.append(re.escape(next(chars, "\\")))
            elif ch == "%":
                out.append(".*")
            elif ch == "_":
                out.append(".")
            else:
                out.append(re.escape(ch))
        rx = re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)
        self._filters.append(lambda r: r.get(col) is not None and bool(rx.match(str(r.get(col)))))
        return self

    def is_(self, col, value):
        want_null = value in (None, "null")
        self._filters.append(
            lambda r: (r.get(col) is None) if want_null else (r.get(col) is not None))
        return self

    def not_(self):  # pragma: no cover - guard
        raise NotImplementedError("FakeSupabase does not support not_")

    def gte(self, col, value):
        self._filters.append(lambda r: r.get(col) is not None and r.get(col) >= value)
        return self

    def lte(self, col, value):
        self._filters.append(lambda r: r.get(col) is not None and r.get(col) <= value)
        return self

    def order(self, col, desc=False, **_kw):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    maybe_single = single

    # -- execution ------------------------------------------------------------
    def _matches(self, row):
        return all(f(row) for f in self._filters)

    def execute(self):
        rows = self._db.tables.setdefault(self._table, [])
        self._db.calls.append((self._table, self._op, copy.deepcopy(self._payload)))
        if self._op == "select":
            out = [copy.deepcopy(r) for r in rows if self._matches(r)]
            if self._order:
                col, desc = self._order
                out.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
            if self._limit is not None:
                out = out[: self._limit]
            if getattr(self, "_single", False):
                return SimpleNamespace(data=out[0] if out else None)
            return SimpleNamespace(data=out)
        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for p in payloads:
                row = {"id": new_id(self._table), **copy.deepcopy(p)}
                rows.append(row)
                out.append(copy.deepcopy(row))
            return SimpleNamespace(data=out)
        if self._op == "update":
            out = []
            for r in rows:
                if self._matches(r):
                    r.update(copy.deepcopy(self._payload))
                    out.append(copy.deepcopy(r))
            return SimpleNamespace(data=out)
        if self._op == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            keys = (self._on_conflict or "id").split(",")
            out = []
            for p in payloads:
                hit = next((r for r in rows
                            if all(r.get(k) == p.get(k) for k in keys)), None)
                if hit is None:
                    hit = {"id": new_id(self._table)}
                    rows.append(hit)
                hit.update(copy.deepcopy(p))
                out.append(copy.deepcopy(hit))
            return SimpleNamespace(data=out)
        if self._op == "delete":
            gone = [r for r in rows if self._matches(r)]
            self._db.tables[self._table] = [r for r in rows if not self._matches(r)]
            return SimpleNamespace(data=[copy.deepcopy(r) for r in gone])
        raise AssertionError(self._op)


class _Rpc:
    def __init__(self, db, name, params):
        self._db, self._name, self._params = db, name, params

    def execute(self):
        fn = self._db.rpcs.get(self._name)
        if fn is None:
            raise AssertionError(f"FakeSupabase has no rpc {self._name!r}")
        return SimpleNamespace(data=fn(**self._params))


class _Bucket:
    def __init__(self, storage: "FakeStorage", name: str):
        self._storage, self._name = storage, name

    def _check(self, path):
        if path in self._storage.fail_paths:
            raise RuntimeError(f"storage refused {path}")

    def upload(self, path, content, options=None):
        self._check(path)
        self._storage.objects[(self._name, path)] = content
        return {"Key": path}

    def download(self, path):
        self._check(path)
        return self._storage.objects[(self._name, path)]

    def remove(self, paths):
        for path in paths:
            self._storage.objects.pop((self._name, path), None)
        return paths

    def create_signed_url(self, path, ttl, options=None):
        self._check(path)
        return {"signedURL": f"https://signed.test/{self._name}/{path}"}


class FakeStorage:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail_paths: set[str] = set()

    def from_(self, bucket: str) -> _Bucket:
        return _Bucket(self, bucket)


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.calls: list[tuple] = []
        self.storage = FakeStorage()
        counter = itertools.count(1)
        self.rpcs = {
            "next_case_no": lambda p_prefix: f"{p_prefix}-{next(counter):04d}",
        }

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict | None = None) -> _Rpc:
        return _Rpc(self, name, params or {})

    def rows(self, name: str) -> list[dict]:
        return self.tables.get(name, [])
