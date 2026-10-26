"""Migration 046 — Client Verification moves to stage 1.

TWO HALVES, AND THE PURE ONE IS THE POINT. The whole migration is a branch
REORDER inside an expression that `nar1_case_status._code()` also implements in
Python. Nothing about a reorder fails loudly: the SQL still parses, the view
still builds, every row still gets a status — just a different one from the one
the case's own screen shows. So the check that matters is that the two orders
agree, and it needs no Postgres.

The badge parity against a live database lives in tests/test_migration_024.py,
which drives every reachable state through the real view. This file pins the
order in the SQL TEXT, which is what CI can afford to run on every push.

NAMED `test_migration_046.py` ON PURPOSE. `.github/workflows/backend-ci.yml`
collects DB-backed assertions as `tests/test_migration_*.py`; a file outside
that glob would never run in the `migrations` job.
"""
import importlib.util
import os
import re

from services import nar1_case_status as ncs

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    """Comments and whitespace out — what Postgres would actually be asked."""
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _status_order(sql: str) -> list[str]:
    """The workflow statuses in the order the CASE expression tests them.

    `ELSE` as well as `THEN`: the last branch is `ELSE 'signing'`, and a
    matcher that only saw THEN would quietly drop it — which is the one branch
    a reorder is most likely to strand.
    """
    body = sql.split("WORKFLOW-STATUS-EXPRESSION-START")[1] \
              .split("WORKFLOW-STATUS-EXPRESSION-END")[0]
    return re.findall(r"(?:THEN|ELSE) '([a-z_]+)'", body)


M046 = "046_client_verification_is_the_first_stage.py"


# --------------------------------------------------------------------------- #
#  No database needed — and these are the ones the dashboard depends on
# --------------------------------------------------------------------------- #

def test_the_client_branches_sit_above_data_verification():
    """THE MIGRATION, in one assertion.

    If `data_verification` were still tested first, a case whose return has not
    been validated would read Data Verification on the dashboard and Client
    Verification on its own screen — the exact divergence the SQL restatement
    exists to avoid.
    """
    order = _status_order(_migration(M046)._case_view_sql(client_first=True))
    assert order.index("client_verification") < order.index("data_verification")
    assert order.index("client_rejected") < order.index("data_verification")
    assert order.index("awaiting_client") < order.index("data_verification")


def test_closure_and_the_filed_branch_still_beat_every_stage():
    """Unchanged by the reorder, and it must stay that way: a closed case is
    closed whatever stage its filing is in, and a return CR already holds wears
    CR's answer rather than a stage of ours."""
    sql = _migration(M046)._case_view_sql(client_first=True)
    order = _status_order(sql)
    assert order[0] == "closed"
    # The CR branch is a COALESCE, not a literal, so it does not appear in
    # `order` — assert its position in the text instead.
    body = sql.split("WORKFLOW-STATUS-EXPRESSION-START")[1]
    assert body.index("manual_receipt_present") < body.index("'client_rejected'")
    assert body.index("manual_receipt_present") < body.index("'data_verification'")


def test_the_sql_order_is_the_python_order():
    """Branch for branch against `nar1_case_status._code`, which is the claim
    the expression's own comment makes.

    Read out of the Python by driving it, not by parsing it: a case is built
    for each branch that can only be answered by that branch, and the order the
    answers come out in is compared with the SQL's."""
    draft = {"stage": "draft"}
    validated = {"stage": ncs.STAGE_VALIDATED}
    signed = {"stage": ncs.STAGE_SIGNED}

    expected = [
        # closed beats everything
        ncs._code({"closed_at": "2026-01-01", "client_approved": False}, signed),
        # then the client, in its own order
        ncs._code({"client_approved": False}, draft),
        ncs._code({}, draft),
        ncs._code({"verification_sent_at": "2026-01-01"}, draft),
        # then the data
        ncs._code({"verification_sent_at": "2026-01-01",
                   "client_approved": True}, draft),
        # then the signature
        ncs._code({"verification_sent_at": "2026-01-01",
                   "client_approved": True}, signed),
        ncs._code({"verification_sent_at": "2026-01-01",
                   "client_approved": True}, validated),
    ]
    assert expected == [
        "closed", "client_rejected", "client_verification", "awaiting_client",
        "data_verification", "submission", "signing",
    ]

    sql_order = _status_order(_migration(M046)._case_view_sql(client_first=True))
    # The filed branch is a COALESCE and contributes no literal, so drop it from
    # the Python side too by comparing only the codes the SQL spells out.
    assert sql_order == [
        "closed", "client_rejected", "client_verification", "awaiting_client",
        "data_verification", "submission", "signing",
    ]


def test_the_downgrade_restores_043s_view_exactly():
    """Byte for byte, once comments and whitespace are out.

    046's `_case_view_sql(client_first=False)` is a hand-restatement of 043's
    `_case_view_sql(cr_status=True)`. If they ever differ, `alembic downgrade`
    leaves a view that is nearly — but not quite — what the rest of the system
    expects, and nothing would notice until somebody needed the rollback.
    """
    m46 = _migration(M046)
    m43 = _migration("043_nar1_cr_document_status.py")
    assert _normalise(m46._case_view_sql(client_first=False)) == \
        _normalise(m43._case_view_sql(cr_status=True))


def test_the_migrations_stage_lists_match_the_services():
    """The view's `live` and `filed` lists are copied constants. One that drifts
    silently reclassifies every case it covers."""
    from services import nar1_cases

    m46 = _migration(M046)
    assert tuple(m46.CR_FILED_STAGES) == tuple(nar1_cases.CR_FILED_STAGES)
    assert m46.FILING_WINDOW_DAYS == ncs.FILING_WINDOW_DAYS


def test_the_new_column_is_added_and_dropped_by_name():
    """`verification_xml` is what lets the case say which fields moved after the
    client approved. A downgrade that left it behind would leave a column
    nothing writes and nothing reads."""
    src = open(os.path.join(_HERE, "alembic", "versions", M046),
               encoding="utf-8").read()
    assert "ADD COLUMN IF NOT EXISTS verification_xml text" in src
    assert "DROP COLUMN IF EXISTS verification_xml" in src


def test_the_recreate_restates_the_grants():
    """DROP VIEW discards them, and Supabase's default privileges GRANT ALL on
    every new relation in `public` to anon and authenticated. A recreate that
    forgot this would publish every case row through PostgREST — approval state
    and statutory receipts included."""
    m46 = _migration(M046)
    assert "REVOKE ALL ON public.nar1_case_registry FROM anon" in m46._CASE_GRANTS
    assert ("REVOKE ALL ON public.nar1_case_registry FROM authenticated"
            in m46._CASE_GRANTS)
    assert ("GRANT SELECT ON public.nar1_case_registry TO service_role"
            in m46._CASE_GRANTS)
