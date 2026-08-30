"""Days-to-anniversary as a computed, never-stored value.

Levi 2026-08-16: "i dont want to store this date in database it doesnt make
sense since it changes every day". Correct — a stored column would be wrong by
morning. A VIEW computes on read and persists nothing, so it is right every day.

Why it has to be server-side at all: the Company listing paginates over ~5,930
rows. Sorting or filtering the 50 rows the server happened to send answers the
wrong question — "the soonest anniversary on page 1" is not "the soonest
anniversary", and it looks correct while being wrong. PostgREST cannot order or
filter on an expression, so the expression becomes a relation. Same reason
009_pbi39_person_registry_view.py exists.

TIME ZONE. Pinned to Asia/Hong_Kong, never bare CURRENT_DATE. Supabase runs UTC
and Hong Kong is UTC+8, so for the first eight hours of every HK working day
CURRENT_DATE is still yesterday — the frontend column (which derives its "today"
the same way, see frontend/src/lib/anniversary.js) would print one number while
this view sorted by another.

SIGNED, not absolute. Negative means the anniversary has PASSED and the return
is still inside the 42-day statutory filing window; positive counts down to the
next one. That ordering is the point: a company 12 days past its anniversary is
353 days from the next, so an unsigned "days remaining" sort buries exactly the
companies that need attention. `<= 60` catches both the upcoming 60 days and
everything still filable.

Says NOTHING about whether a NAR1 was filed. That fact does not exist in DEV —
2 of 7,959 NAR1 form_filings carry filed_date — so any "overdue" claim here
would be invented. See PRD §6 W-3.

Verified before shipping: this expression was evaluated against all 5,457 real
incorporation dates in DEV and compared with the shipped anniversary.js,
including 29 February cases. Zero disagreements, range -42..322.

Read-only and additive. No table is altered, no data is written.
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

FILING_WINDOW_DAYS = 42


def upgrade() -> None:
    # The anniversary of `d` falling in year `y`.
    #
    # 29 February is the whole reason this is a function: make_date(2026, 2, 29)
    # raises, it does not clamp. LEAST(day, last day of that month) pins it to
    # the 28th in a common year, matching the frontend helper exactly.
    #
    # IMMUTABLE is honest here — the result depends only on the arguments. The
    # view below is what makes the final value time-varying, not this.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.anniversary_in(d date, y integer)
        RETURNS date
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
          SELECT make_date(
            y,
            EXTRACT(MONTH FROM d)::int,
            LEAST(
              EXTRACT(DAY FROM d)::int,
              EXTRACT(DAY FROM (
                make_date(y, EXTRACT(MONTH FROM d)::int, 1)
                + INTERVAL '1 month' - INTERVAL '1 day'
              ))::int
            )
          );
        $$;
    """)

    # Hong Kong's today, as a plain date. Kept as its own function so the zone is
    # named once and every caller agrees on when "today" starts.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.hk_today()
        RETURNS date
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
          SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Hong_Kong')::date;
        $$;
    """)

    op.execute(f"""
        CREATE OR REPLACE VIEW public.company_registry
        WITH (security_invoker = true) AS
        SELECT
          e.*,
          a.last_on AS last_anniversary,
          a.next_on AS next_anniversary,
          CASE
            -- No incorporation date -> no anniversary to measure against. The
            -- LEFT JOIN leaves last_on NULL for exactly those rows.
            WHEN a.last_on IS NULL THEN NULL
            -- Passed, still inside the filing window: count UP, negative.
            WHEN (public.hk_today() - a.last_on) <= {FILING_WINDOW_DAYS}
              THEN -(public.hk_today() - a.last_on)
            -- Otherwise the live fact is the next anniversary: count DOWN.
            ELSE (a.next_on - public.hk_today())
          END::int AS days_to_anniversary
        FROM public.entities e
        LEFT JOIN LATERAL (
          SELECT
            CASE WHEN y.this_yr <= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int - 1)
            END AS last_on,
            CASE WHEN y.this_yr >= public.hk_today() THEN y.this_yr
                 ELSE public.anniversary_in(e.incorporation_date,
                        EXTRACT(YEAR FROM public.hk_today())::int + 1)
            END AS next_on
          FROM (
            SELECT public.anniversary_in(e.incorporation_date,
                     EXTRACT(YEAR FROM public.hk_today())::int) AS this_yr
          ) y
        ) a ON e.incorporation_date IS NOT NULL;
    """)

    # Supabase-only roles, guarded so the migration also applies to the vanilla
    # Postgres the CI `migrations` job runs (same idiom as 009). That job creates
    # `authenticated` and nothing else, so an unguarded GRANT fails the build.
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            GRANT SELECT ON public.company_registry TO anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            GRANT SELECT ON public.company_registry TO authenticated;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            GRANT SELECT ON public.company_registry TO service_role;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.company_registry;")
    op.execute("DROP FUNCTION IF EXISTS public.hk_today();")
    op.execute("DROP FUNCTION IF EXISTS public.anniversary_in(date, integer);")
