"""services/table_filters — the per-column filter grammar.

The value of these tests is the REFUSALS. A filter this module fails to
understand and drops silently is indistinguishable, on a paginated listing,
from a filter that matched every row — so every unknown column, unsupported op
and unparseable value has to raise rather than be skipped.
"""
import pytest

from services import table_filters as tf

SPEC = {
    "company_name": tf.text(),
    "status": tf.enum({"live", "ceased"}),
    "days_to_anniversary": tf.number(),
    "updated_at": tf.timestamp(),
    "incorporation_date": tf.date(),
}


class FakeQuery:
    """Records what would reach PostgREST, in order."""

    def __init__(self):
        self.calls = []
        self._negate = False

    @property
    def not_(self):
        self._negate = True
        return self

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args):
            prefix = "not." if self._negate else ""
            self._negate = False
            self.calls.append((prefix + name, *args))
            return self
        return call


def apply(raw):
    q = FakeQuery()
    return tf.apply(q, tf.parse(raw, SPEC)).calls


# ── parsing ───────────────────────────────────────────────────────────────

def test_no_filters_is_no_filters():
    assert tf.parse(None, SPEC) == []
    assert tf.parse([], SPEC) == []


def test_unknown_column_is_refused():
    with pytest.raises(tf.FilterError, match="Cannot filter by 'secret'"):
        tf.parse(["secret:contains:x"], SPEC)


def test_op_the_column_kind_does_not_support_is_refused():
    # `contains` on a number would become a PostgREST `ilike` on an integer.
    with pytest.raises(tf.FilterError, match="Cannot apply 'contains'"):
        tf.parse(["days_to_anniversary:contains:5"], SPEC)


def test_malformed_filter_is_refused():
    with pytest.raises(tf.FilterError, match="Malformed"):
        tf.parse(["company_name"], SPEC)


def test_a_value_may_contain_colons():
    # Split on the first two only — a timestamp or a name is not a delimiter.
    f = tf.parse(["company_name:eq:A: B: C"], SPEC)[0]
    assert f.value == "A: B: C"


def test_enum_value_outside_the_domain_is_refused():
    with pytest.raises(tf.FilterError, match="Unknown value for 'status': dissolved"):
        tf.parse(["status:in:live,dissolved"], SPEC)


def test_enum_naming_no_values_is_refused():
    with pytest.raises(tf.FilterError, match="names no values"):
        tf.parse(["status:in:"], SPEC)


def test_non_numeric_value_on_a_number_column_is_refused():
    with pytest.raises(tf.FilterError, match="not a number"):
        tf.parse(["days_to_anniversary:gte:soon"], SPEC)


def test_negative_numbers_are_accepted():
    # A passed anniversary counts negative (migration 019); the default
    # registry view opens on -42, so this is the common case, not an edge one.
    assert tf.parse(["days_to_anniversary:gte:-42"], SPEC)[0].value == -42


def test_bad_date_is_refused():
    with pytest.raises(tf.FilterError, match="YYYY-MM-DD"):
        tf.parse(["updated_at:gte:last tuesday"], SPEC)
    with pytest.raises(tf.FilterError, match="not a real date"):
        tf.parse(["updated_at:gte:2026-02-31"], SPEC)


def test_empty_text_value_is_refused():
    # An empty box is "no filter", which the frontend drops before sending. One
    # arriving anyway is a bug, and matching the empty string is not the fix.
    with pytest.raises(tf.FilterError, match="has no value"):
        tf.parse(["company_name:contains:"], SPEC)


def test_absurd_filter_counts_and_lengths_are_refused():
    with pytest.raises(tf.FilterError, match="Too many filters"):
        tf.parse(["company_name:eq:x"] * 25, SPEC)
    with pytest.raises(tf.FilterError, match="too long"):
        tf.parse([f"company_name:eq:{'x' * 201}"], SPEC)


def test_an_enum_column_must_declare_its_domain():
    with pytest.raises(ValueError, match="must declare its values"):
        tf.Column("enum")


# ── applying ──────────────────────────────────────────────────────────────

def test_contains_becomes_a_wildcarded_ilike():
    assert apply(["company_name:contains:acme"]) == [("ilike", "company_name", "%acme%")]


def test_exact_text_is_case_insensitive_and_unwildcarded():
    assert apply(["company_name:eq:ACME"]) == [("ilike", "company_name", "ACME")]


def test_like_metacharacters_in_a_term_are_escaped():
    # "69_" must find the literal underscore, not "691".
    assert apply(["company_name:contains:a_b%c"]) == [
        ("ilike", "company_name", r"%a\_b\%c%")
    ]


def test_an_asterisk_stays_a_wildcard():
    # PostgREST rewrites `*` to `%` on the raw text, so an escaped `\*` would
    # arrive as `\%` and search for a literal PERCENT — typing `*` would
    # silently find the wrong thing. Left through, it behaves like the wildcard
    # an asterisk usually is.
    assert apply(["company_name:contains:ac*me"]) == [
        ("ilike", "company_name", "%ac*me%")
    ]


def test_enum_becomes_an_in_list():
    assert apply(["status:in:live,ceased"]) == [("in_", "status", ["live", "ceased"])]


def test_a_range_is_two_filters_on_one_column():
    assert apply(["days_to_anniversary:gte:-42", "days_to_anniversary:lte:60"]) == [
        ("gte", "days_to_anniversary", -42),
        ("lte", "days_to_anniversary", 60),
    ]


def test_empty_on_text_covers_null_and_the_empty_string():
    # The ETL wrote both. Finding only one of them under-reports by however many
    # rows the import happened to write the other way.
    assert apply(["company_name:empty:"]) == [
        ("or_", "company_name.is.null,company_name.eq.")
    ]


def test_notempty_on_text_excludes_both():
    assert apply(["company_name:notempty:"]) == [
        ("not.is_", "company_name", "null"),
        ("neq", "company_name", ""),
    ]


def test_empty_on_a_number_is_null_only():
    # There is no empty-string integer, and `col.eq.` against one is a PG error.
    assert apply(["days_to_anniversary:empty:"]) == [
        ("is_", "days_to_anniversary", "null")
    ]


def test_a_timestamp_upper_bound_covers_the_whole_day():
    # A timestamptz compared with a bare date: without this, picking the same
    # day for both bounds — the commonest way anyone uses a date range — returns
    # nothing at all.
    assert apply(["updated_at:gte:2026-06-01", "updated_at:lte:2026-06-01"]) == [
        ("gte", "updated_at", "2026-06-01T00:00:00+00:00"),
        ("lt", "updated_at", "2026-06-02T00:00:00+00:00"),
    ]


def test_a_plain_date_column_is_compared_as_written():
    # incorporation_date is a DATE, so no end-of-day expansion belongs on it.
    assert apply(["incorporation_date:lte:2026-06-01"]) == [
        ("lte", "incorporation_date", "2026-06-01")
    ]
