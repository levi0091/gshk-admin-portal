"""Migration 057 -- the case registry after ND2A/ND2B met the duplicate-submission fix.

050, 052 and 054 each restate `nar1_case_registry` from 047's text, so applied
after 056 they silently drop 056's four view differences (the Submission stage
for `submitting` / `submission_unknown`, the stale-claim read, the filing pick).
057 restates the final ND2 view with them put back. The pure half runs in the
`unit` job; the DB-backed half is test_migration_024's parity table, which drives
every stage, including the two new ones, through the view and `_code`.
"""
import importlib.util
import os
import re
from unittest.mock import patch

import pytest

from services import nar1_case_status as st
from services.tpsi import filings

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M054 = "054_cr_status_removed.py"
M056 = "056_nar1_submit_outcome_unknown.py"
M057 = "057_case_view_after_nd2_reland.py"


def _migration(name: str):
    path = os.path.join(_HERE, "alembic", "versions", name)
    spec = importlib.util.spec_from_file_location(name.split(".")[0], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def _statements(direction: str) -> list[str]:
    m57 = _migration(M057)
    seen: list[str] = []
    with patch.object(m57.op, "execute", side_effect=lambda sql: seen.append(str(sql))):
        getattr(m57, direction)()
    return seen


def test_057_revises_055_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    m57 = _migration(M057)
    assert (m57.revision, m57.down_revision) == ("057", "055")
    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    assert script.get_heads() == ["059"]


def test_the_chain_runs_through_056_before_the_nd2_migrations():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(os.path.join(_HERE, "alembic.ini")))
    chain = []
    rev = script.get_revision("057")
    while rev is not None and rev.revision != "049":
        chain.append(rev.revision)
        rev = script.get_revision(rev.down_revision) if rev.down_revision else None
    assert list(reversed(chain)) == [
        "051", "056", "050", "052", "053", "054", "055", "057"]


def test_the_stage_lists_are_056s_and_the_pythons():
    m56, m57 = _migration(M056), _migration(M057)
    assert set(m57.LIVE_STAGES) == set(m56.LIVE_STAGES)
    assert set(m57.SUBMISSION_STAGES) == set(m56.SUBMISSION_STAGES)
    assert m57.STALE_CLAIM_SECONDS == m56.STALE_CLAIM_SECONDS == filings.STALE_CLAIM_SECONDS
    assert set(m57.NEW_STAGES) == {filings.STAGE_SUBMITTING,
                                   filings.STAGE_SUBMISSION_UNKNOWN}


def test_the_view_has_056s_four_differences_and_the_nd2_branches():
    sql = _normalise(_migration(M057).view_sql())
    live = ", ".join(f"'{s}'" for s in _migration(M056).LIVE_STAGES)
    submission = ", ".join(f"'{s}'" for s in _migration(M056).SUBMISSION_STAGES)
    # 1 and 2: the stages are live, and they are AT Submission.
    assert f"filing_stage NOT IN ({live})" in sql
    assert f"WHEN base.filing_stage IN ({submission}) THEN 'submission'" in sql
    # 3: a stale claim reads as the unknown outcome it is.
    assert "tf.stage = 'submitting'" in sql
    assert f"interval '{filings.STALE_CLAIM_SECONDS} seconds'" in sql
    assert "THEN 'submission_unknown'" in sql
    # 4: the pick prefers a row CR may hold.
    assert ("ORDER BY (tf.stage IN ('submitted', 'edrive', 'submitting', "
            "'submission_unknown')) DESC") in sql
    # ND2's own branches survive: the manual route and the e-Sign route.
    assert "base.signing_method = 'manual'" in sql
    assert "base.signing_method = 'esign'" in sql
    # ...and the e-Sign branch knows a submit in flight is not Signing.
    esign = sql[sql.index("base.signing_method = 'esign'"):]
    assert "'submitting'" in esign.split("THEN 'signing'")[0]
    assert "'submission_unknown'" in esign.split("THEN 'signing'")[0]


def test_the_view_keeps_054s_removal_of_the_cr_status():
    sql = _migration(M057).view_sql()
    for gone in ("cr_doc_status", "cr_status_checked_at", "'registered'",
                 "cr_not_checked", "cr_pending", "cr_registered"):
        assert gone not in sql, gone
    assert "THEN 'filed'" in sql


def test_upgrade_replaces_the_view_and_downgrade_restores_054s():
    up, down = _statements("upgrade"), _statements("downgrade")
    assert up[0].startswith("DROP VIEW IF EXISTS public.nar1_case_registry")
    assert "CREATE VIEW public.nar1_case_registry" in up[1]
    assert "GRANT SELECT ON public.nar1_case_registry TO service_role" in up[2]
    assert _normalise(down[1]) == _normalise(_migration(M054).view_sql())
    assert len(up) == len(down) == 3


@pytest.mark.parametrize("stage", ["submitting", "submission_unknown"])
def test_the_pythons_esign_branch_agrees_with_the_views(stage):
    """An e-Sign ND2 case, checked, with a submit in flight or unknown, is at
    Submission -- not back at Signing -- in the Python as in the SQL."""
    case = {"verification_sent_at": "2026-10-01T00:00:00Z", "client_approved": True,
            "form_code": "Nd2a", "signing_method": "esign",
            "data_checked_at": "2026-10-02T00:00:00Z"}
    assert st.derive(case, {"stage": stage})["code"] == "submission"
