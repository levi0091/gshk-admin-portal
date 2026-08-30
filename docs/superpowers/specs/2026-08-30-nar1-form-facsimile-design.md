# NAR1 form facsimile — design

**Status:** BUILT and merged to `dev` (f4918de). Kept as the record of why.
**Date:** 2026-08-30
**Item:** Levi's request 2 — "the pdf viewed for the NAR1 is not the actual NAR1
form. It needs to be in the format of the actual NAR1 form."

---

## The problem

`services/nar1_pdf.py` renders a *review document*: a branded table of the
fields in CR's validated XML. Its own docstring says so and defends it —
"Deliberately NOT a facsimile of CR's printed form."

That was a reasonable call for the admin's pre-submit double-confirm. It is the
wrong document for the person it is actually shown to. During Client
Verification the portal emails a director a PDF and asks them to approve their
own company's statutory return. A director knows what Form NAR1 looks like;
they have signed them for years. They do not know what our field table means,
and they cannot check it against anything.

So the deliverable is the real form: CR's own layout, filled.

## What we have to work with

Three documents in `docs/`, all from CR:

| File | What it is | Use |
|---|---|---|
| `NAR1_fillable.pdf` | CR's official form, 27 pages, **365 AcroForm fields** | The template we fill |
| `NAR1(private)_Specimen-e.pdf` | CR's worked example, private company, flattened | Ground truth for the field map |
| `NAR1(public)_Specimen-e.pdf` | Same, public company | Ground truth for the public variant |
| `Example_Sch1and2_NAR1.pdf` | 11 pages of Schedule 1/2 edge cases | Schedule rules (joint holders, death, forfeiture, transfer) |

### The fillable form's structure

Pages 1–15 carry fields; pages 16–27 are the printed *Notes for Completion* and
must be **dropped from output** — nobody needs twelve pages of guidance notes
attached to a return they are being asked to approve.

| Page | Section |
|---|---|
| 1 | 1–5: company name, business name, type, business nature, return date, financial period |
| 2 | 6–11: registered office, email, phone, mortgages, members of a company without share capital, share capital |
| 3 | 12A company secretary (natural person) |
| 4 | 12B company secretary (body corporate) |
| 5 | 13A director (natural person) |
| 6 | 13B director (body corporate) |
| 7 | 13C reserve director |
| 8 | 14 members, 15 company records, signature block |
| 9 | Schedule 1 — non-listed company members |
| 10 | Schedule 2 — listed company members |
| 11–15 | Continuation Sheets A–E |

### The field-naming problem, and the way around it

Every field is generically named — `fill_7_P.3`, `cb_1_P.5` — with no tooltips
and no semantic hints. There is no map in the file.

**But the geometry is unambiguous.** Page 1's widget rects read straight off the
printed form: three checkboxes at y=536 sitting exactly under 私人公司 / 公眾公司 /
擔保有限公司, three date boxes at y=447 for DD/MM/YYYY, four stacked full-width
boxes at y=205–337 for the registered office. Verified by probe.

**And the specimens verify it.** The specimens are flattened — no form fields —
but their *rendered text carries coordinates*, and those coordinates land inside
the fillable's widget rects. Probed and confirmed:

```
widget @(393.0, 447.2)  ->  "23 05 2025"            # date return made up
widget @(184.9, 307.2)  ->  "Room 8801-8803, 88/F"  # registered office line 1
```

So the map is not guesswork: derive it from geometry, then check every derived
name against what CR itself put in that box in the specimen.

One trap: the specimens carry **annotation callouts** ("Please fill in the first
8 digits of the business registration number") positioned near the boxes they
describe. Those are instructional text, not filled values, and must not be
mistaken for ground truth. The probe already hit this on the BR number field.

## Design

### Three units

**1 · `services/nar1_form_map.py` — the field map (generated, committed)**

A build-time script (`scripts/build_nar1_form_map.py`) reads `NAR1_fillable.pdf`,
clusters the 365 widgets by page and position, cross-checks against both
specimens, and emits a dict of semantic name → qualified field name:

```python
FIELDS = {
    "br_number":            "fill_1_P.1",
    "company_name_en":      "fill_1_P.2",
    "type_private":         "cb_1_P.1",
    "return_date_dd":       "fill_1_P.9",
    ...
}
```

**Committed, not derived at runtime.** If CR revises the form, the diff is
visible in review rather than silently shifting every value one box to the left.
The generator stays in the repo so the map can be rebuilt and re-verified.

**2 · `services/nar1_form_fill.py` — the filler**

Takes CR's `validated_xml` and returns PDF bytes. Same data source as today's
`nar1_pdf.py`, for the reason its docstring already gives: `validated_xml` is
the document CR is actually holding, and it carries fields CR filled itself
(`compNameE`, `compNameC`, `coyStatus`, `formCode`, `natureDesc`,
`dateReturnMadeUp`). Showing the client anything else risks approving one
document and filing another.

Responsibilities:
- fill pages 1–8 from the XML
- tick section 3 by company type; a private company skips section 5
- emit Schedule 1 (non-listed) or Schedule 2 (listed)
- emit Continuation Sheets A–E on overflow
- drop pages 16–27
- flatten the output, so the client cannot edit the form they are approving

**3 · Overflow — the part that must not be skipped**

The base form holds exactly one of most things. Real companies exceed it, and a
truncated statutory return **misstates the company**. Rules, from the form's own
instructions:

| Overflow | Sheet |
|---|---|
| >1 natural-person secretary | Continuation Sheet A |
| >1 body-corporate secretary | Continuation Sheet B |
| >1 natural-person director | Continuation Sheet C |
| >2 body-corporate directors | Continuation Sheet D |
| company records not at the registered office | Continuation Sheet E |
| >2 members, or >1 share class | additional Schedule 1 / 2 |

Continuation sheets are page templates: to emit a second one, the page is
duplicated and its fields re-filled. Every sheet repeats the return date and BR
number in its header, so each page stands alone.

### Where it is used

Replaces `nar1_pdf.render` at both call sites — `routers/cases.py:680` (client
verification) and `routers/tpsi.py:719` (pre-submit preview) — per Levi's
choice of "replace everywhere, full overflow".

`nar1_pdf.py` is then **deleted**, not left beside the new one. Two renderers
for the same statutory document is exactly the arrangement where a fix lands in
one and not the other.

### Library

`pypdf` — already a dependency, already used to probe these files, and it does
AcroForm field updates and page duplication. No new dependency.

CJK: today's renderer registers `MSung-Light` by name and does not embed it.
The fillable form ships its own fonts and CR's field appearances reference them,
so filled Chinese should render from the form's own resources. **To be confirmed
during the build** — if the form's fonts do not cover a name, the fallback is to
embed a Traditional Chinese face, which the current renderer deliberately
avoided to keep a ~10MB TTF out of the repo. Flagging it now because it is the
one open technical risk.

## Testing

- **Map verification** — for every field the specimens fill, assert the derived
  semantic name is the one whose box CR put that value in. This is the test that
  makes the whole thing trustworthy, and it runs against CR's own documents.
- **Golden render** — build a company matching the private specimen, render, and
  assert each value lands in the box the specimen has it in. Same for public.
- **Overflow** — three secretaries produce Sheet A; three members produce a
  second Schedule 1; assert no particular is dropped. This is the regression
  that matters most: silent truncation is the failure that would reach CR.
- **Notes stripped** — the output has no page 16+.
- **Flattened** — output has no editable fields.
- **Company type** — private ticks private and omits section 5; public ticks
  public and fills it; guarantee ticks guarantee and uses section 10 not 14.

## Out of scope

- Chinese-language filing. CR's notes require the form be completed consistently
  in one language; the mapper already files English (`"language": "E"`).
- CD-ROM/DVD-ROM member lists (section 14's third option). Schedule 1/2 covers
  what GSHK files.
- Hand-editing the fillable PDF. It is CR's document; we fill it, we do not
  modify it.

## Q1 — answered

Levi, 2026-08-30: the Submission screen keeps the wireframe_v11 field layout on
screen, and its **Download NAR1** button serves the facsimile. So both PDF call
sites render the real form and `nar1_pdf.py` is retired.

## What the build changed about this spec

- **`coyStatus` is absent** from a real validated return, not filled by CR as
  the schema implies. Company type is resolved from `entities.company_type`
  instead, defaulting to private (NULL on 5,987 of 5,998 DEV companies).
- **`dateReturnMadeUp` is dd/mm/yyyy**, not ISO. `split_date` takes both.
- **The field numbering is not in reading order.** `shares_held` is `fill_16`
  in one schedule slot and `fill_27` in the other. The verification tests
  caught it; the map is written from measured positions throughout.
- **Duplicated pages need their fields renamed** — AcroForm names are
  document-wide, so two Sheet C copies otherwise share one field.
- **CJK was not a problem.** The form's own fonts render Chinese names; no
  embedded face was needed. That risk is closed.
- **Page order is ascending template page**, which is CR's printed order. The
  first version shipped continuation sheets ahead of the schedules.
