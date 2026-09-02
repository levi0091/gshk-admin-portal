"""Per-column table filters — one grammar, applied IN THE DATABASE.

Every listing in this portal paginates: the Company Registry is ~5,930 rows
served 50 at a time, the Person Registry more. So a column filter has to reach
PostgREST, for the same reason sorting already does (`_SORTABLE` in every
router). Filtering the 50 rows the server happened to send would look right,
narrow nothing, and quietly answer a different question than the one asked —
and on a paginated listing the operator has no way to tell.

WIRE FORM — a repeated query parameter:

    ?filter=company_name:contains:acme&filter=status:in:live,ceased

`<column>:<op>:<value>`, split on the FIRST TWO colons only, so a value may
contain colons (a timestamp, a name) without escaping. A column may appear more
than once; PostgREST ANDs them, which is how a range is expressed:

    ?filter=days_to_anniversary:gte:-42&filter=days_to_anniversary:lte:60

WHITELISTED, NOT ESCAPED. `column` and `op` both reach PostgREST's filter
clause, so neither may ever be caller-controlled free text — each router
declares a `spec` naming exactly which of its columns are filterable and what
kind of thing each holds. An unknown column or an op the column's kind does not
support is a 422, never a silently dropped filter: a filter the server drops
looks exactly like a filter that matched everything.

The VALUE is data and is passed as data — through supabase-py's positional
filter methods (`q.ilike(col, val)`), which build `column=op.value` and encode
the value themselves. That is the reason nothing here reassembles an `or_()`
string out of user input: `or_()` takes a comma-and-dot-delimited grammar, so a
term containing either character stops being data (see
`nar1_cases._escape_filter_value`, which exists because the search box does need
`or_()`). The two `or_()` uses below interpolate only a whitelisted COLUMN name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date, timedelta as _timedelta

#: Ops each column kind understands. The op is a supabase-py method name in
#: most cases, which is exactly why this mapping is closed.
_OPS_FOR_KIND = {
    # `eq` on text is case-INSENSITIVE exact (an `ilike` with no wildcards).
    # A registry operator typing "acme" means the company called ACME; making
    # them match the stored casing would be a puzzle, not a filter.
    "text": {"contains", "eq", "empty", "notempty"},
    "enum": {"in", "empty", "notempty"},
    "bool": {"eq"},
    "number": {"gte", "lte", "eq", "empty", "notempty"},
    "date": {"gte", "lte", "eq", "empty", "notempty"},
    "timestamp": {"gte", "lte", "empty", "notempty"},
}

#: A URL carrying more than this is not an operator filtering a table.
_MAX_FILTERS = 24
_MAX_VALUE = 200

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Column:
    """One filterable column.

    `values` closes an enum's domain, so `status:in:<anything>` cannot put an
    unknown string into a PostgREST `in.()` list.
    """
    kind: str
    values: frozenset[str] | None = None

    def __post_init__(self):
        if self.kind not in _OPS_FOR_KIND:
            raise ValueError(f"unknown column kind '{self.kind}'")
        if self.kind == "enum" and not self.values:
            raise ValueError("an enum column must declare its values")


def text() -> Column:
    return Column("text")


def enum(values) -> Column:
    return Column("enum", frozenset(values))


def number() -> Column:
    return Column("number")


def date() -> Column:
    return Column("date")


def timestamp() -> Column:
    return Column("timestamp")


def boolean() -> Column:
    return Column("bool")


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    #: Already coerced to the column's kind: int for number, list[str] for an
    #: enum `in`, str otherwise. `empty`/`notempty` carry None.
    value: object = None
    kind: str = "text"


class FilterError(ValueError):
    """A filter the server will not run. Routers turn this into a 422."""


def parse(raw: list[str] | None, spec: dict[str, Column]) -> list[Filter]:
    """Validate raw `col:op:value` strings against one table's spec.

    Raises FilterError on anything unrecognised. Never returns a partially
    understood filter — half a comparison narrows the wrong set.
    """
    if not raw:
        return []
    if len(raw) > _MAX_FILTERS:
        raise FilterError(f"Too many filters (max {_MAX_FILTERS})")

    out: list[Filter] = []
    for item in raw:
        parts = item.split(":", 2)
        if len(parts) < 2:
            raise FilterError(f"Malformed filter '{item}' — expected column:op:value")
        column, op = parts[0], parts[1]
        value = parts[2] if len(parts) == 3 else ""

        col = spec.get(column)
        if col is None:
            raise FilterError(f"Cannot filter by '{column}'")
        if op not in _OPS_FOR_KIND[col.kind]:
            raise FilterError(f"Cannot apply '{op}' to '{column}'")
        if len(value) > _MAX_VALUE:
            raise FilterError(f"Filter value for '{column}' is too long")

        if op in ("empty", "notempty"):
            out.append(Filter(column, op, None, col.kind))
            continue

        if col.kind == "enum":
            picked = [v for v in value.split(",") if v != ""]
            if not picked:
                raise FilterError(f"Filter on '{column}' names no values")
            unknown = [v for v in picked if v not in col.values]
            if unknown:
                raise FilterError(
                    f"Unknown value for '{column}': {', '.join(sorted(unknown))}"
                )
            out.append(Filter(column, op, picked, col.kind))
            continue

        if col.kind == "number":
            try:
                out.append(Filter(column, op, int(value), col.kind))
            except ValueError:
                raise FilterError(f"'{value}' is not a number") from None
            continue

        if col.kind in ("date", "timestamp"):
            if not _DATE_RE.match(value):
                raise FilterError(
                    f"Filter on '{column}' must be a YYYY-MM-DD date, got '{value}'"
                )
            try:
                _date.fromisoformat(value)
            except ValueError:
                raise FilterError(f"'{value}' is not a real date") from None
            out.append(Filter(column, op, value, col.kind))
            continue

        if value == "":
            raise FilterError(f"Filter on '{column}' has no value")
        out.append(Filter(column, op, value, col.kind))

    return out


def apply(q, filters: list[Filter]):
    """Add every filter to a supabase-py query, in order.

    Caller's job to do this inside whatever builds the COUNT queries too.
    Filtering only the page query leaves the pager and the tab counts quoting
    a total for a set nobody is looking at.
    """
    for f in filters:
        q = _apply_one(q, f)
    return q


def _apply_one(q, f: Filter):
    col, op = f.column, f.op

    if op == "empty":
        # Text and enums have two ways of being blank — SQL NULL and the empty
        # string — and the ETL produced both. A "no value" filter that found
        # only one of them would under-report by however many rows the import
        # happened to write the other way.
        if f.kind in ("text", "enum"):
            return q.or_(f"{col}.is.null,{col}.eq.")
        return q.is_(col, "null")

    if op == "notempty":
        q = q.not_.is_(col, "null")
        if f.kind in ("text", "enum"):
            q = q.neq(col, "")
        return q

    if f.kind == "enum":
        return q.in_(col, f.value)

    if f.kind == "text":
        if op == "contains":
            # `%` and `_` are LIKE metacharacters. A BRN search for "69_" must
            # not quietly match "691" — the operator typed a literal.
            return q.ilike(col, f"%{_escape_like(str(f.value))}%")
        return q.ilike(col, _escape_like(str(f.value)))

    if f.kind == "timestamp":
        # A timestamptz column against a plain date: `lte` has to mean "up to
        # the end of that day", or picking the same date for both bounds
        # returns nothing at all — the commonest way anyone uses a date range.
        if op == "lte":
            return q.lt(col, _next_day(str(f.value)))
        return q.gte(col, f"{f.value}T00:00:00+00:00")

    return getattr(q, op)(col, f.value)


def _next_day(day: str) -> str:
    return f"{_date.fromisoformat(day) + _timedelta(days=1)}T00:00:00+00:00"


def _escape_like(value: str) -> str:
    """Neutralise SQL LIKE metacharacters inside a user's search term.

    `%` and `_` reach SQL's LIKE untouched, so a BRN search for "69_" would
    otherwise match "691" — the operator typed a literal. Backslash goes first
    because it is LIKE's own escape character.

    `*` IS DELIBERATELY LEFT ALONE, and stays a wildcard. PostgREST rewrites it
    to `%` before the value reaches SQL, and it does so on the raw text — so an
    escaped `\\*` arrives as `\\%`, which SQL then reads as a literal PERCENT.
    Escaping it here would mean typing `*` silently searches for `%`. Letting it
    through means `*` works the way a search box's asterisk usually does, which
    is a far smaller surprise, and no company name in this book contains one.
    """
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
