"""Who signs on the body corporate's behalf — `nar1_cases.signatory_capacity`.

THE PROBLEM THIS SOLVES. GSHK is the company secretary of the companies it
files for, and GSHK is a body corporate. A body corporate does not sign: a
natural person signs on its behalf, and CR's `selectCapacityDesc` says which
one, from a controlled vocabulary of 15 values ("Director of the Company
Secretary (Body Corporate)", and so on). Nothing in the company profile can
tell us which — it depends on who at GSHK actually signs.

Until now `nar1_mapper` REFUSED to map any such company rather than guess, and
the Data Verification screen showed a red "this company cannot be filed as a
NAR1 yet" panel. Since every real GSHK client is in exactly that position, the
practical effect was that no real company could be prepared at all. Levi
2026-08-30: the operator knows their own filing arrangement, so this becomes a
choice they make, not a refusal we hand them.

WHY IT LIVES ON THE CASE and not on the entity or the filing:

  - Not on `entities`: it describes an act of signing, not the company. The
    same company can be signed for by different people in different years.
  - Not on `tpsi_filings`: it has to be chosen BEFORE a filing row exists —
    `POST /tpsi/filings/prepare` is what consumes it, and prepare is what
    creates the filing. A column on the filing could never be read in time.
  - `restart_verification` deliberately does NOT clear it. Restarting discards
    the CR-signed snapshot because the DATA changed; who signs did not.

NO CHECK CONSTRAINT, and that is deliberate. CR's vocabulary is CR's, it has
already changed once within this project's life, and a database constraint that
disagreed with `cr_vocabularies.py` would refuse a value CR accepts — failing
closed on the wrong authority. Validation lives in `services/nar1_cases.py`
against the same table the mapper checks, so there is exactly one vocabulary.

Nullable, no default, no backfill: an unset capacity means "nobody has chosen
yet", which is the honest state of every existing row.

Applied to DEV ONLY. Nothing applied to PROD.
"""
import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None

TABLE = "nar1_cases"
COLUMN = "signatory_capacity"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Text(),
            nullable=True,
            comment=(
                "CR selectCapacityDesc for this return's signatory. Chosen by "
                "the operator from cr_vocabularies.CAPACITY_BODY_CORPORATE (or "
                "CAPACITY_INDIVIDUAL for a natural-person signer). NULL means "
                "not yet chosen. Not constrained here on purpose: CR owns the "
                "vocabulary and services/nar1_cases.py validates against it."
            ),
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN, schema="public")
