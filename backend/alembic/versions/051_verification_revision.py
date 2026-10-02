"""Every verification email a client receives carries its revision number.

Levi 2026-10-02: "if we have to restart verification because some data was
wrong and send the email again.. we would like the new email ... to say
[Rev. 2] or [Rev. 3] and up the version for each email we send for
confirmation. and the previous revision sent to client the confirmation link
should be disabled or expired." For NAR1 here; ND2A and ND2B share both tables
and therefore this migration.

`nar1_cases.verification_revision` IS HOW MANY VERIFICATION EMAILS WENT OUT.
0 means the client has never been written to. The send computes `+ 1` before
it mails — the number has to be in the subject — and STORES it only once at
least one message has left, alongside `verification_sent_at` and for the same
reason: a send Resend refused entirely reached nobody, so the next attempt is
that same revision, not the one after it. A client must never receive Rev. 3
having never seen a Rev. 2.

It is NOT reset by Restart verification. A restart discards the return the
client was shown; it does not un-send the email, and the client still has it.
The next send after a restart is therefore the next revision, which is exactly
the case the request was about.

`nar1_client_approvals.revision` IS WHICH SEND A LINK BELONGS TO, and it is the
SECOND LOCK on an earlier revision's link. The first is unchanged: issuing a
new revision's tokens supersedes every outstanding one (`nar1_approvals.issue`).
But that is a write, and a token store that would not write left the old link
live — so the public page and the auto-approval job now also refuse a token
whose revision is below the case's. Same shape as `closed_at` in
`public_approval._decided`: the supersede normally gets there first, and this
is what holds when it did not.

LEGACY TOKENS STAY NULL, deliberately. Their send can be numbered only by
inference (`dense_rank` over `sent_at`), and an inference that came out one
LOW would mark a director's current link stale and refuse a valid approval —
DEV has a case, NAR-2026-0053, with two sends on the trail and one token batch,
which is precisely that shape. NULL means "the revision lock does not apply";
the outcome-based supersede still does, and the next send kills them anyway.

THE BACKFILL IS THE MOST THE RECORD SUPPORTS, from three sources, because each
misses something the others catch:

  EMAIL_SENT audit rows      every send since PBI-11, including those that went
                             without a Confirm link (no token was issued)
  distinct token `sent_at`   one per `issue()` call, which survives a send
                             whose audit write failed (audit is best-effort)
  verification_sent_at       a case mailed before either existed is at least 1

Measured on DEV before writing this: 22 cases have sends; the audit count is
the larger on one, equal on the rest, and seven carry `verification_sent_at`
with no trail at all (ETL'd state).

`trg_set_updated_at` IS DISABLED AROUND THE BACKFILL. It stamps `updated_at =
now()` on every UPDATE of `nar1_cases` (044 exempts only the CR heartbeat), so
a backfill that let it fire would re-date every case ever mailed to the moment
this migration ran — and the dashboard's Last Updated column would rank them by
"when was the schema changed", the same answer for all of them. 044 documents
the identical trap from the other side.

NO VIEW CHANGE. `nar1_case_registry` lists its columns explicitly (024..047),
so an added table column does not alter it — and the case screen reads the
table through `nar1_cases.composite`, which spreads the whole row.

050 IS NOT SKIPPED BY ACCIDENT. It is the ND2A/ND2B officer-changes migration
on the `nd2a_nd2b` branch, not yet merged and applied nowhere (DEV was at 049
when this was written). This migration reaches `dev` first, so 050 is
re-pointed to revise 051 on that branch: the chain runs 049 -> 051 -> 050.
Renumbering 050 instead would have rewritten fifty-odd references across work
still in progress.

Revision ID: 051
Revises: 049
"""
from alembic import op

revision = "051"
down_revision = "049"
branch_labels = None
depends_on = None

_CASES = "public.nar1_cases"
_TOKENS = "public.nar1_client_approvals"

#: The trigger 003 created and 044 narrowed. Named once so the disable and the
#: re-enable cannot name different things.
_TRIGGER = "trg_set_updated_at"

#: `services/audit_events.EMAIL_SENT`, and the entity type the verification
#: send writes it under (`routers/cases._audit_target`).
_EMAIL_SENT = "EMAIL_SENT"
_CASE_ENTITY = "nar1_case"

_BACKFILL = f"""
    WITH sends AS (
      SELECT entity_id, count(*) AS n
        FROM public.audit_log
       WHERE action_type = '{_EMAIL_SENT}' AND entity_type = '{_CASE_ENTITY}'
       GROUP BY entity_id
    ), batches AS (
      SELECT nar1_case_id, count(DISTINCT sent_at) AS n
        FROM {_TOKENS}
       GROUP BY nar1_case_id
    )
    UPDATE {_CASES} c
       SET verification_revision = r.n
      FROM (
        SELECT c2.id,
               GREATEST(COALESCE(s.n, 0), COALESCE(b.n, 0),
                        CASE WHEN c2.verification_sent_at IS NOT NULL
                             THEN 1 ELSE 0 END) AS n
          FROM {_CASES} c2
          LEFT JOIN sends s   ON s.entity_id = c2.id::text
          LEFT JOIN batches b ON b.nar1_case_id = c2.id
      ) r
     WHERE r.id = c.id AND r.n > 0
"""

_COMMENTS = f"""
    COMMENT ON COLUMN {_CASES}.verification_revision IS
      'How many client-verification emails have gone out for this case. 0 = '
      'never sent. Rev. 2 onward is printed on the email. Not reset by a '
      'verification restart. Migration 051.';
    COMMENT ON COLUMN {_TOKENS}.revision IS
      'The verification_revision this link was mailed with. A link below the '
      'case''s current revision is refused. NULL on links issued before '
      'migration 051, which the revision lock does not apply to.';
"""


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {_CASES} ADD COLUMN verification_revision integer "
        "NOT NULL DEFAULT 0 "
        "CONSTRAINT nar1_cases_verification_revision_nonneg "
        "CHECK (verification_revision >= 0)"
    )
    op.execute(
        f"ALTER TABLE {_TOKENS} ADD COLUMN revision integer "
        "CONSTRAINT nar1_client_approvals_revision_positive "
        "CHECK (revision IS NULL OR revision >= 1)"
    )
    op.execute(f"ALTER TABLE {_CASES} DISABLE TRIGGER {_TRIGGER}")
    op.execute(_BACKFILL)
    op.execute(f"ALTER TABLE {_CASES} ENABLE TRIGGER {_TRIGGER}")
    op.execute(_COMMENTS)


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TOKENS} DROP COLUMN IF EXISTS revision")
    op.execute(f"ALTER TABLE {_CASES} DROP COLUMN IF EXISTS verification_revision")
