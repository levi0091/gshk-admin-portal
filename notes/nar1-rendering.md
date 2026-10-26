# Rendered NAR1: dates and boxes CR fills

_Moved out of `CLAUDE.md` verbatim (nothing edited) so it is not loaded into every agent turn. Read it before changing: the rendered NAR1 (dates, presenter reference, flat PDF)._

> **This reverses "an absent value means today in Hong Kong"** (2026-09-04), which was itself a reversal of "blank when the caller supplies nothing". Dating an unfiled copy *today* fixed an empty box by putting a wrong date in it, two ways at once: a director approving on 28 October saw 28 October on a return CR would not receive until 1 November, and one return downloaded on two days showed two different dates. What CR prints there is the day CR got the form; until then there is no such day, and a blank box says so where a plausible date does not. **`signature_date()` returns `""` for anything it cannot read** — a fallback date is indistinguishable on the page from a real one.
>
> **Not `signed_at`.** Signing and submitting are separate CR calls: a return signed at 23:55 and submitted at 00:10 was filed the *next* day, and one signed but never submitted was never filed at all. **Both roads to the register count** — the e-Sign path writes `tpsi_filings.submitted_at`, while the off-portal path never touches the filing row (it is signed on paper and lodged by hand) and records the day on `nar1_cases.manual_submitted_at`. Reading only the filing row re-dated every manually filed return to whatever day somebody downloaded it. `filed_on` is **pure** — both rows are passed in — because a query hidden in it would run inside the renderers' refusal paths and inside every router test that patches the renderer but not Supabase.
>
> **Hong Kong, not UTC** — Railway and Supabase both run UTC, and a return filed at 01:00 in the office is 17:00 the previous day there. Only a *timestamp* is converted; a plain date is taken verbatim.
>
> The date is **not in CR's XML** either way — CR hands none back — so this is the portal's rendered copy only, and `compare.py` composes both sides undated so a filing date can never be reported as a change the client did not approve.
