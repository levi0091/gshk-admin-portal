"""Rewrite Viewpoint's sub-national country codes to the ones CR can file.

THE BUG THIS CLEARS. `CGAHCHBAABBG DIRECTOR COMPANY LIMITED` sat at Data
Verification refusing to become a NAR1:

    registered office: no CR region code is known for country 'HK-CH' — CR's
    Country & Region sheet (worksheet v1.0.14) carries no code, alpha-2 or
    English name matching it

'HK-CH' is Viewpoint's Chinese-labelled Hong Kong (香港). Someone picked it out
of the old country dropdown — which was fed by `lookup_values.country`, 270
Viewpoint rows including three labelled only in Chinese — and it stored a code
CR has never heard of. Commit 24290c7 fixed the dropdown; it could not fix the
rows already written, and a stored value nothing offers any more is a value
nobody can correct by picking again.

WHAT IS REWRITTEN, AND WHY IT IS NOT A GUESS. `VIEWPOINT_SUBDIVISIONS` in
`services/tpsi/forms/cr_vocabularies.py` carries all twenty of the codes CR has
no entry for, each mapped to the ISO alpha-2 of the one CR row its own Viewpoint
label sits inside: 香港/澳門/台灣 to HK/MO/TW, England and Scotland and Wales and
Northern Ireland to the UNITED KINGDOM, Alderney and Sark to GUERNSEY (GBR1, not
GBR — CR treats them as separate jurisdictions), Labuan to MALAYSIA, the eight US
states to UNITED STATES, and Zaire to the DEMOCRATIC REPUBLIC OF THE CONGO,
which is what it was renamed to in 1997 and NOT the neighbouring 'CONGO'.

`cr_vocabularies._build` refuses to import if any target is not on CR's sheet,
so this migration cannot write a code CR would reject.

THIS REVERSES A DELIBERATE DECISION. `backfill_cr_form_fields` used to leave
these alone: "'HK-CH' is not a spelling of anything -- it needs a human to
re-pick it, not a guess from here." The caution was right about guessing and
wrong about the cost of waiting: the profile looked correct, so nobody knew
there was anything to re-pick until a filing was refused. Levi's call,
2026-09-03.

ALSO DEACTIVATES the twenty rows in `lookup_values.country`. No screen reads
that category any more — every CR-validated country field moved to `cr_country`
in 24290c7 — but leaving a poisoned option active in a table whose whole job is
to be offered is how this happened the first time.

DOWNGRADE PUTS BACK THE LOOKUP ROWS AND NOTHING ELSE. The rewritten addresses
are not restored: the previous values were unfilable, the correct ones are
indistinguishable from rows that always held them, and re-poisoning live
statutory data to satisfy symmetry would be a worse bug than the one this fixes.

Applied to DEV. PROD has not been cut over.
"""
import sqlalchemy as sa
from alembic import op

from services.tpsi.forms.cr_vocabularies import VIEWPOINT_SUBDIVISIONS

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

#: Every column the profile screens render from CR's own country list, and which
#: therefore has to HOLD one of its keys. Same three as
#: `etl/backfill_cr_form_fields._COUNTRY_COLUMNS`; kept in step by the test.
COUNTRY_COLUMNS = (
    ("entities", "incorporation_place"),
    ("person_identity_documents", "issuing_country"),
    ("addresses", "country"),
)


def upgrade() -> None:
    conn = op.get_bind()

    # Case-insensitively, because Viewpoint's own casing is not guaranteed and
    # a row stored 'hk-ch' is the same bug. The comparison is on the trimmed
    # value for the same reason.
    for table, column in COUNTRY_COLUMNS:
        for source, alpha2 in VIEWPOINT_SUBDIVISIONS.items():
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = :alpha2 "
                    f"WHERE upper(btrim({column})) = :source"
                ),
                {"alpha2": alpha2, "source": source},
            )

    # The options themselves. `is_active` rather than DELETE: these rows are a
    # mirror of Viewpoint's own lookup table, and a row that exists there should
    # still be explicable here — it just must never be offered.
    conn.execute(
        sa.text(
            "UPDATE lookup_values SET is_active = false "
            "WHERE category = 'country' AND upper(btrim(code)) = ANY(:codes)"
        ),
        {"codes": list(VIEWPOINT_SUBDIVISIONS)},
    )


def downgrade() -> None:
    # Only the lookup rows. See the module docstring: putting 'HK-CH' back into
    # an address would re-break a filing that now works, and nothing
    # distinguishes the rows this migration corrected from the thousands that
    # were always right.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE lookup_values SET is_active = true "
            "WHERE category = 'country' AND upper(btrim(code)) = ANY(:codes)"
        ),
        {"codes": list(VIEWPOINT_SUBDIVISIONS)},
    )
