"""Audit trail: WHICH record, and WHICH module.

Revision ID: 034
Revises: 033
Create Date: 2026-09-04

Levi 2026-09-04: "in a lot of actions it is not clear what case or company or
person it is referring to."

He is right, and it is not one bug. Four separate paths wrote rows the trail
cannot name:

  * PERSON events put the person's name in `company_name` but nothing at all in
    the identity-document route, so editing a passport number read as "Change
    Compliance Details" against a blank cell.
  * TPSI FILING events carried a filing uuid and no company whatsoever — the
    entire CR half of the trail was anonymous.
  * VIEWPOINT rows whose KeyCode is a person's RefCode resolved against
    `entities`, missed, and fell back to printing the raw Viewpoint key.
  * Nothing anywhere distinguished a company edit from a person edit from a
    NAR1 workflow step, so the one question an auditor actually starts from —
    "show me everything that happened in post-incorporation this week" — could
    not be asked.

FOUR COLUMNS, denormalized like `company_name` and `action_label` before them
(migration 012), because the audit trail must stay readable after the record it
describes is deleted, and must be filterable without a join over 226k+ rows:

    module        which surface: post_incorporation | body_corporate |
                  natural_person | documents | cr_filing
    subject_kind  case | company | person
    subject_id    the record's id, so the cell is a link
    subject_ref   the identifier a human quotes — case no / BRN / ID number

`company_name` is UNCHANGED and keeps holding the subject's NAME. It has always
held a person's name on person rows; this only writes down what it meant. The
pair renders as "name (ref)", except for a case, where the case number leads:

    case      NAR1-2026-0042 (Kanenas Holding Limited)
    company   Kanenas Holding Limited (69123456)
    person    Ilze TSERKEZIS (A123456(7))

BACKWARD COMPATIBLE WITH VIEWPOINT. Every imported row is backfilled below from
data Viewpoint already supplied: `source_keycode` is a RefCode, and it resolves
to an entity or a person, which gives kind, id, name and reference. What
Viewpoint has no equivalent of is left NULL rather than invented — no imported
row is labelled post_incorporation, documents or cr_filing, because Viewpoint
recorded none of those. A NULL module renders as a dash, which is the truth.

THE IMPORTED HISTORY IS BACKFILLED BY A SCRIPT, NOT BY THIS MIGRATION, and that
split is not a shortcut. `audit_log` holds 226k+ Viewpoint rows; the single
UPDATE that resolves them ran past Supabase's statement timeout when it was in
here, and even raised it would hold one alembic transaction open long enough for
the connection to be dropped mid-way — which is precisely why
`etl/backfill_audit_context.py` exists (see its docstring) and why migration
012's own backfill lives there too. It runs each step in its own transaction and
is idempotent, so it is safe to re-run and safe to resume:

    cd backend && python -m etl.backfill_audit_context        # --dry-run first

Run it after this migration, and again after any fresh Viewpoint import. Until
it runs, imported rows simply have no module and no subject — the trail reads
exactly as it did before, never wrongly.

What IS done here is the G-FlowDesk side, which is a few thousand rows: those
are the ones a deploy starts writing the moment it lands, so they must not
depend on anybody remembering to run a script.

IDEMPOTENT. Every statement is `ADD COLUMN IF NOT EXISTS` or an UPDATE with an
`IS NULL` guard, so re-running changes nothing and a partially-applied run
finishes cleanly.

NOT INSERT-ONLY VIOLATIONS. PBI-11 forbids UPDATE and DELETE *policies* on
`audit_log` so no authenticated client can rewrite history. A migration runs as
the owner and is the only sanctioned way to add context to rows that already
exist — exactly as migration 012 did when it added `company_name`.
"""
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


#: Kept in step with services/audit_subject.MODULES and
#: frontend/src/lib/auditVocabulary.js. Not a Postgres ENUM: the audit trail
#: takes whatever a writer sends (there is no FK on `event_code` either), and a
#: type that rejects an unseeded value would turn a labelling slip into a failed
#: audit write, which is the one failure mode this table must not have.
MODULES = ("post_incorporation", "body_corporate", "natural_person",
           "documents", "cr_filing")

SUBJECT_KINDS = ("case", "company", "person")

#: Five G-FlowDesk codes that migration 012 lists in its `_NATIVE` seed and that
#: DEV does not actually have. Verified live on 2026-09-04: 28 of the portal's
#: 33 codes are in `audit_event_types` and these five are not, so every document
#: upload, version, deletion, company-flag change and shareholder removal has
#: been rendering with a BLANK action ever since.
#:
#: That is the same defect migration 022 exists to repair, and it is in scope
#: here rather than in a migration of its own because it is the other half of
#: the same complaint: a row whose Action cell is empty says no more about what
#: happened than one whose subject is empty says about whom it happened to. It
#: also matters more now than it did yesterday, because `documents` has just
#: become a module you can filter the trail down to.
#:
#: `origin` and `category` are BOTH explicit. The column defaults to
#: origin='viewpoint', which would file G-FlowDesk actions as inherited
#: Viewpoint history.
MISSING_NATIVE_CODES = [
    ("GF_DOC_UPLOADED", "Document Uploaded", "document"),
    ("GF_DOC_VERSION", "Document Version Added", "document"),
    ("GF_DOC_DELETED", "Document Deleted", "document"),
    ("GF_FLAGS_CHANGED", "Client / Corporate-Party Flags Changed", "entity"),
    ("GF_SHAREHOLDER_REMOVED", "Shareholder Removed", "party"),
]


def upgrade() -> None:
    # The native backfills below still have to look at every row to find the
    # few thousand that are theirs, and Supabase's default statement timeout is
    # shorter than that takes. LOCAL, so it lasts exactly as long as this
    # migration's own transaction.
    op.execute("SET LOCAL statement_timeout = '1800s'")

    # The five codes that never made it into the registry (see above). Seeded
    # before anything else, so the re-label below has something to find.
    values = ", ".join(
        f"('{code}', '{name}', '{category}', 'g_flowdesk')"
        for code, name, category in MISSING_NATIVE_CODES
    )
    op.execute(
        f"INSERT INTO public.audit_event_types (code, name, category, origin) "
        f"VALUES {values} ON CONFLICT (code) DO NOTHING"
    )
    op.execute("""
        UPDATE public.audit_log a
        SET action_label = t.name
        FROM public.audit_event_types t
        WHERE a.action_label IS NULL AND a.event_code = t.code
    """)

    op.execute("""
        ALTER TABLE public.audit_log
          ADD COLUMN IF NOT EXISTS module       TEXT,
          ADD COLUMN IF NOT EXISTS subject_kind TEXT,
          ADD COLUMN IF NOT EXISTS subject_id   UUID,
          ADD COLUMN IF NOT EXISTS subject_ref  TEXT
    """)

    # Filtering columns. `subject_ref` gets a trigram-free btree because the
    # header filter on it is an exact/prefix match, not a substring scan; the
    # free-text search box already goes through `company_name`.
    for column in ("module", "subject_kind", "subject_id", "subject_ref"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_audit_log_{column} "
            f"ON public.audit_log({column})"
        )

    # ---------------------------------------------------------------- native
    # G-FlowDesk rows written before this migration. `entity_type` says what
    # the row is about; `case_id` holds an ENTITY id by repo convention
    # (routers/cases.py::_audit_target) and `entity_id` the record's own id.
    #
    # TPSI FILING ROWS ARE THE EXCEPTION, and are repaired first, from
    # `tpsi_filings` rather than from what the audit row happens to hold.
    #
    # Two routes wrote `nar1_case_id` into `case_id`, which is a different id
    # space — those rows are invisible to every company-scoped query, which is
    # the trail they belong in. Reading the FILING gives both ids from the one
    # place that is authoritative about them, so the repair is right whether the
    # row carries the old value or the new one, and re-running it is a no-op
    # rather than a second, different guess.
    op.execute("""
        UPDATE public.audit_log a
        SET subject_kind = 'case',
            subject_id   = f.nar1_case_id,
            subject_ref  = c.case_no,
            module       = 'cr_filing',
            case_id      = COALESCE(f.entity_id, a.case_id),
            company_name = COALESCE(a.company_name, e.company_name)
        FROM public.tpsi_filings f
        LEFT JOIN public.nar1_cases c ON c.id = f.nar1_case_id
        LEFT JOIN public.entities   e ON e.id = f.entity_id
        WHERE a.source = 'g_flowdesk'
          AND a.entity_type = 'tpsi_filing'
          AND a.subject_kind IS NULL
          AND a.entity_id = f.id::text
          AND f.nar1_case_id IS NOT NULL
    """)

    # A filing with no case behind it (an NNC1, a one-off) is about the company.
    op.execute("""
        UPDATE public.audit_log a
        SET subject_kind = 'company',
            subject_id   = f.entity_id,
            subject_ref  = e.br_number,
            module       = 'cr_filing',
            case_id      = f.entity_id,
            company_name = COALESCE(a.company_name, e.company_name)
        FROM public.tpsi_filings f
        LEFT JOIN public.entities e ON e.id = f.entity_id
        WHERE a.source = 'g_flowdesk'
          AND a.entity_type = 'tpsi_filing'
          AND a.subject_kind IS NULL
          AND a.entity_id = f.id::text
          AND f.nar1_case_id IS NULL
          AND f.entity_id IS NOT NULL
    """)

    # Everything else. Note what is NOT here: a `tpsi_filing` row whose filing
    # has since been deleted gets NO subject rather than a guess. Its `case_id`
    # may hold either id space, and labelling it 'company' while pointing at a
    # case id is worse than leaving the cell empty — it renders a name that is
    # not the record, and a link to a 404.
    op.execute("""
        UPDATE public.audit_log
        SET subject_kind = CASE
              WHEN entity_type = 'nar1_case' THEN 'case'
              WHEN entity_type = 'person'    THEN 'person'
              WHEN entity_type IN ('entity', 'share_class',
                                   'entity_record_location') THEN 'company'
              -- A document or an address hangs off EITHER a company or a
              -- person, so the id is checked rather than assumed. A person's
              -- address is written with the PERSON id in `case_id`
              -- (routers/persons.py), which a bare "case_id is not null" test
              -- would read as a company and then link to a 404.
              WHEN entity_type IN ('document', 'address') THEN CASE
                     WHEN EXISTS (SELECT 1 FROM public.entities e
                                  WHERE e.id = audit_log.case_id) THEN 'company'
                     WHEN EXISTS (SELECT 1 FROM public.persons p
                                  WHERE p.id = audit_log.case_id) THEN 'person'
                     WHEN case_id IS NULL THEN 'person'
                   END
            END
        WHERE source = 'g_flowdesk' AND subject_kind IS NULL
    """)

    op.execute("""
        UPDATE public.audit_log
        SET module = CASE
              WHEN entity_type = 'nar1_case' THEN 'post_incorporation'
              WHEN entity_type = 'person'    THEN 'natural_person'
              WHEN entity_type IN ('entity', 'share_class',
                                   'entity_record_location') THEN 'body_corporate'
              WHEN entity_type = 'address'
                   THEN CASE WHEN subject_kind = 'person'
                             THEN 'natural_person' ELSE 'body_corporate' END
              WHEN entity_type = 'document' THEN 'documents'
              WHEN entity_type IN ('tpsi', 'tpsi_filing', 'tpsi_credential')
                   THEN 'cr_filing'
            END
        WHERE source = 'g_flowdesk' AND module IS NULL
    """)

    # subject_id. entity_id is TEXT and can hold a non-uuid ('shared', for the
    # shared CR credential), so every cast is guarded by a regex - an unguarded
    # `::uuid` aborts the whole statement on the first bad row.
    op.execute(r"""
        UPDATE public.audit_log
        SET subject_id = CASE
              WHEN subject_kind = 'case'   THEN entity_id::uuid
              -- A person's own row carries the person id in entity_id; a
              -- document or address about them carries it in case_id.
              WHEN subject_kind = 'person' THEN COALESCE(
                     CASE WHEN entity_type = 'person' THEN entity_id::uuid END,
                     case_id)
              WHEN subject_kind = 'company' THEN case_id
            END
        WHERE source = 'g_flowdesk' AND subject_id IS NULL
          -- The regex guards the cast: entity_id is TEXT and can hold a
          -- non-uuid ('shared', for the shared CR credential). An unguarded
          -- `::uuid` aborts the whole statement on the first bad row.
          AND (entity_id ~ '^[0-9a-fA-F-]{36}$' OR subject_kind = 'company')
    """)

    # ------------------------------------------------ references, native rows
    # The identifier a human quotes. Filled last and only where still empty.
    # Only native rows have a subject at this point — the imported ones are the
    # script's job — so these joins stay small.
    op.execute("""
        UPDATE public.audit_log a
        SET subject_ref = e.br_number
        FROM public.entities e
        WHERE a.subject_kind = 'company'
          AND a.subject_ref IS NULL
          AND a.subject_id = e.id
          AND e.br_number IS NOT NULL
    """)

    op.execute("""
        UPDATE public.audit_log a
        SET subject_ref = c.case_no
        FROM public.nar1_cases c
        WHERE a.subject_kind = 'case'
          AND a.subject_ref IS NULL
          AND a.subject_id = c.id
          AND c.case_no IS NOT NULL
    """)

    # The person's primary identity document, ordered exactly like
    # `person_registry`'s lateral join (migration 009) so the trail quotes the
    # same document the registry screen shows.
    op.execute("""
        UPDATE public.audit_log a
        SET subject_ref = (
              SELECT d.id_number
              FROM public.person_identity_documents d
              WHERE d.person_id = a.subject_id
              ORDER BY d.is_primary DESC, d.created_at ASC
              LIMIT 1
            )
        WHERE a.subject_kind = 'person'
          AND a.subject_ref IS NULL
          AND a.subject_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM public.person_identity_documents d
            WHERE d.person_id = a.subject_id
          )
    """)

    # A native row that still has no name but does have a resolvable subject:
    # the identity-document route recorded none at all before this change.
    op.execute("""
        UPDATE public.audit_log a
        SET company_name = p.full_name
        FROM public.persons p
        WHERE a.company_name IS NULL
          AND a.subject_kind = 'person'
          AND a.subject_id = p.id
    """)

    op.execute("""
        UPDATE public.audit_log a
        SET company_name = e.company_name
        FROM public.entities e
        WHERE a.company_name IS NULL
          AND a.subject_kind IN ('company', 'case')
          AND a.case_id = e.id
    """)


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in MISSING_NATIVE_CODES)
    op.execute(f"DELETE FROM public.audit_event_types WHERE code IN ({codes})")
    # The labels written from them are left alone: they are the correct names
    # for those actions whether or not the registry row exists, and a row that
    # goes back to reading blank is strictly worse.

    for column in ("module", "subject_kind", "subject_id", "subject_ref"):
        op.execute(f"DROP INDEX IF EXISTS public.idx_audit_log_{column}")
    op.execute("""
        ALTER TABLE public.audit_log
          DROP COLUMN IF EXISTS module,
          DROP COLUMN IF EXISTS subject_kind,
          DROP COLUMN IF EXISTS subject_id,
          DROP COLUMN IF EXISTS subject_ref
    """)
    # The `company_name` values this migration filled in are deliberately NOT
    # reverted: they are the same fact migration 012's column has always held,
    # and unpicking which of them predate this run is not possible.
