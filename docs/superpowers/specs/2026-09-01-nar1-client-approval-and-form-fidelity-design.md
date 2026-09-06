# NAR1 — client self-approval, form fidelity, and the pre-submit drift gate

**Date:** 2026-09-01
**Author:** Claude (with Levi)
**Status:** Design — awaiting review before an implementation plan is written

Seven changes requested against the NAR1 workflow. Three of them add
subsystems this repo does not have today: a public unauthenticated write
surface, a scheduled job, and a third section in the Storage bucket. The rest
are bounded changes to code that already exists.

They are specified together because two of them are entangled — the client
email (§2) cannot be written until the approval button (§5) and the deadline
it prints both exist — but they are **built in five blocks**, sequenced in §9.

---

## 1 · Deterministic fonts on the generated NAR1

### The defect, measured

The complaint was that the NAR1 attached to the client's email and the NAR1 in
the portal's preview render in different fonts, and that the font is wrong.
Both halves have the same cause, and it is not a styling choice.

Measured on a rendered test return from `services/nar1_form/fill.py`:

| Property | Measured |
|---|---|
| Text fields | 131 |
| Fields carrying a value | 53 |
| Valued fields with an appearance stream (`/AP`) | **53 — all of them** |
| Fields whose `/DA` is `/PMingLiU 12 Tf` | 125 |
| Font referenced inside those appearance streams | `/PMingLiU` (52), `/TimesNewRoman` (1) |
| Is `/PMingLiU` embedded in the document? | **No** |
| `NeedAppearances` | `true` |

There are **two independent defects**, and the first is not the one it looks
like from the outside:

1. **`NeedAppearances=true` tells conforming viewers to discard the appearance
   streams and regenerate them from `/DA`.** Acrobat and Word/Outlook obey;
   Chrome's pdfium largely renders the existing `/AP` instead. Same bytes, two
   different rendering paths — which is precisely the reported symptom, the
   email attachment and the portal preview disagreeing.
2. **Whichever path a viewer takes, the font is `/PMingLiU` and it is not
   embedded.** It is a Traditional Chinese face; a Windows machine substitutes
   one thing, a Mac another, a Linux container a third. So the font is both
   wrong and unstable across platforms.

An earlier reading of this counted 78 fields as having "no appearance stream".
That was wrong — those 78 are the *empty* fields, which correctly have none.
Every field that carries a value already has a stream. The defect is what the
streams point at, and the flag that invites them to be thrown away.

### The target, measured

Fonts extracted from `docs/Kanenas Holding Limited NAR1 2026.pdf`, which is
the CR-produced return GSHK regards as correct:

| Value | Font | Size |
|---|---|---|
| Field values — names, addresses, amounts, dates | Times New Roman **Bold** | 10pt |
| Business Registration Number, header box | Times New Roman **Bold** | 14pt |
| Company name, field 1 | Times New Roman **Bold** | 12pt |
| Presenter block, page 1 | Times New Roman Regular | 10pt |

The Arial / MingLiU throughout the reference is CR's *printed form*, not
filled data. We do not touch it — it arrives in the template.

### Approach — a baked text layer, verified by spike

Draw the values as a **baked page layer** in embedded fonts, hide the widget
annotations so nothing paints over it, and set `NeedAppearances` **off**.

Rejected: rewriting each widget's `/AP` in place. It leaves the values subject
to the same regeneration flag and requires hand-building CID font dictionaries
for CJK. The overlay uses `reportlab`, **already a dependency of this repo**,
which handles embedding and subsetting itself.

Keeping `/V` is deliberate. A true flatten would also fix the rendering, but
it would break every `values_of()` assertion in `tests/test_nar1_form_fill.py`
and make the document unreadable to anything inspecting it as a form. Writing
the layer *and* keeping `/V` means viewers render our bytes while the data
stays machine-readable.

New module `services/nar1_form/appearance.py`:

- For each widget with a non-empty `/V`, draws the value inside its `/Rect` at
  10pt, shrinking in 0.25pt steps to fit, vertically centred.
- Splits each value into runs by Unicode block, selecting the CJK face
  per-character so a mixed Latin/Chinese value renders correctly.
- Sets `/F` bit 2 (Hidden) on each widget it has drawn, so no viewer paints a
  field box or its own guess of the text over the layer.

**Measured on the spike** (`build_xml()` with a Chinese director name):

| | |
|---|---|
| Values drawn | 53 of 53 |
| `NeedAppearances` in output | `False` |
| Tinos Bold in output | embedded + subsetted |
| Noto Serif TC in output | embedded + subsetted |
| CJK recoverable from the text layer | yes |
| Document size | 1.75 MB → 1.77 MB |

Fonts, committed under `services/nar1_form/fonts/`:

- **Tinos Bold and Tinos Regular** (OFL-1.1). Metric compatibility with
  Times New Roman was **measured, not assumed**: across company names,
  addresses, amounts and emails the advance-width delta at 10pt is **exactly
  0.0000pt**. Nothing wraps or overflows differently. Chosen over shipping
  `timesbd.ttf`, which is Monotype-licensed and cannot be redistributed here.
- **Noto Serif TC** (OFL) for CJK runs.

Two font facts the spike established the hard way, both of which would
otherwise have been discovered mid-implementation:

- **reportlab cannot load PostScript-outline OTF** — it raises
  `TTFError: postscript outlines are not supported`. The CJK face must be a
  TrueType-outline build.
- **The Noto Serif TC variable font's default instance is ExtraLight**, so
  registering the VF directly embeds the wrong weight. It is instanced to
  `wght=700` **once, offline**, with `fontTools.varLib.instancer`, and the
  resulting 10.0 MB static Bold is committed. Doing it offline means
  **`fonttools` is a build-time tool, not a runtime dependency** — nothing new
  is added to `pyproject.toml`'s runtime list.

> Font files live beside the module, **not** under `docs/`, which is gitignored
> repo-wide — a copy there exists on one laptop and is absent from CI, Railway
> and every fresh clone. This is the trap the NAR1 template itself nearly
> shipped into.

### 1b · The form is static — empty pages are still filed

Raised by the client, and confirmed against the reference: CR's NAR1 is a
**fixed nine-page form**. Pages are not dropped when their section is empty.

| Page | Section | Kanenas |
|---|---|---|
| 1 | 1–6 company name, type, return date, registered office | filled |
| 2 | 7–11 email, telephone, charges, **share capital** | filled |
| 3 | 12 Company Secretary A — natural person | **empty, still present** |
| 4 | 12 Company Secretary B — body corporate | filled (GSHK Ltd) |
| 5 | 13 **Directors A — natural person** | filled |
| 6 | 13 Directors B — body corporate | **empty, still present** |
| 7 | 13 Directors C — reserve director | **empty, still present** |
| 8 | 14 Members | filled |
| 9 | Schedule 1 | filled |

`fill.py` emits pages 3–7 only when the matching officer list is non-empty
(`fill.py:520-545`), so a typical private company renders **6 pages instead of
9**, and the page a given section lands on shifts with the company's officer
mix.

**Fix:** always emit pages 1–8 plus Schedule 1 or Schedule 2, regardless of
whether the section has content. Continuation sheets (11–15) stay conditional
— CR's own form says "Use Continuation Sheet C if more than 1 director is a
natural person", so those genuinely are overflow.

This makes the page numbering stable and correct by construction, which is
what resolves §2's page references.

### Tests

- Every text field carrying a value also carries an `/AP`. This is the
  assertion that would have caught the original defect.
- `NeedAppearances` is absent or false.
- No field's effective font resolves to PMingLiU.
- Both Tinos faces are embedded (a `/FontFile2` is present); the CJK face is
  embedded **only** when the document contains CJK.
- A Chinese company name renders through Noto Serif TC, not as blanks or
  `.notdef` boxes.
- Sizes: 10pt values, 14pt BRN, 12pt company name.
- Visual: extend `scripts/shoot-stages.mjs`'s harness approach with a
  rasterised page-1 comparison, so a font regression is visible and not only
  assertable.

---

## 2 · Client verification email — the Confirmation NAR1 Notice wording

`services/email_service.py :: verification_email` is rewritten to the wording
of `docs/Confirmation NAR1 Notice.pdf`, with the company, director and dates
substituted per case.

Structure, following the sample:

1. Greeting by the director's first name.
2. "I enclose herewith the NAR1 for your review. Please carefully check and
   confirm the following:"
3. Heading — "1. NAR1 Form - Signature not required".
4. The page bullets: Page 2 Share capital · Page 5 Director's details ·
   Schedule 1 Shareholder's details.
5. The director's-duty paragraph, the deadline, and the HK$1000 amendment
   warning.
6. **The approval button** (§5).
7. Signature block: the logged-in case worker's display name, "Account
   Manager", and GSHK's office block from the sample.

The deadline renders as **send date + 14 days**, computed from the same value
the auto-approval job reads (§5), so the email and the job can never state
different dates.

### The page numbers are correct — this was our bug, not the sample's

An earlier draft of this spec flagged the sample's page references as wrong,
having measured them against our own six-page output. That was backwards. The
client's point stands: the NAR1 is a **static form**, and CR keeps a section's
page whether or not it has content (§1b).

Against the real nine-page form the sample is exactly right:

| Sample says | Actual |
|---|---|
| Page 2: Share capital | ✓ section 11, page 2 |
| Page 5: Director's details | ✓ section 13A, page 5 |
| Schedule 1: Shareholder's details | ✓ page 9 |

So the references are hardcoded — as chosen — and §1b makes them true. **§2
therefore depends on §1b**, not merely on §1: sending this wording against a
page-dropping renderer would misdirect the client.

### Preserved from the existing design

Table-based markup with inline styles — Outlook renders through Word: no
flexbox, no grid, no reliable `<style>` block. Outfit does not load in most
mail clients, so the fallback stack is the typography. Every interpolated
value stays escaped; company names come out of the Viewpoint ETL and an
unescaped one lands in a client's mailbox as live markup.

### The reversal this makes, stated plainly

`CLAUDE.md` records: *"The message carries no link at all — the client
confirms by replying, and a mail about someone's company filings that
contains a link is the exact shape of the phishing it would train them to
trust."* `test_email_service.py` asserts it.

§5 reverses that decision. It is Levi's to reverse, and it is recorded here
rather than quietly deleted. The mitigations that make the link defensible
are in §5; `CLAUDE.md` and the asserting tests are updated in the same commit,
so the doctrine and the code never disagree.

The reply path is **not** removed. A client who replies is still recorded by
staff through `POST /cases/{id}/verification/response`.

---

## 3 · Client review PDF viewer height

`frontend/src/components/case/StageClientVerification.jsx` — the embedded
`<object>` height is `460 * zoom / 100`. The base becomes **690** (+50%).

The comment above it explains the 460 and must be updated with it, or the next
reader trusts a number the code no longer uses. `ZOOM_MIN`/`ZOOM_MAX` are
unchanged: zoom grows the viewport rather than applying a CSS transform, so
the multiplier still behaves.

---

## 4 · CR receipt upload — manual submission only

Scope: the **manual** (wet-signed, filed off-portal) path. The e-Sign path
receives its receipt from CR in the submit response and is untouched.

### Storage

A third section beside `entity/` and `person/` in `gflowdesk-documents`:

```
receipt/{nar1_case_id}/{version}/{filename}
```

`services/document_service.py :: _OWNER_KINDS` gains `receipt`, and
`_storage_path` handles it. A receipt is owned by a **case**, not a company —
two annual returns for the same company must not collide, and a receipt filed
under the entity would be ambiguous between years.

New `document_types` row seeded by migration: `cr_receipt`, "CR Filing
Receipt", category `filing`.

### API

`POST /cases/{case_id}/manual-receipt` — multipart upload, `tpsi:submit`,
audited `NAR1_MANUAL_RECEIPT_ENTERED`. Refuses a zero-byte file; a zero-byte
upload proves nothing and would still satisfy the gate below. Accepts PDF and
image types only.

`POST /cases/{case_id}/manual-submit` gains a gate: it refuses unless **both**
the typed receipt fields (`caseNo`, `totalAmount` — what the audit trail and
fee reconciliation read) **and** the uploaded file are present. The typed
fields are not derived from the file; nothing parses values out of a scan.

Gate order follows the existing convention in that handler — most specific
first, before the receipt body is examined.

### Frontend

`StageSubmission.jsx`'s manual branch gains an upload control beside the
receipt fields, and the submit button reports which of the two is missing at
the button rather than in a page-level banner.

---

## 5 · Client self-approval

### Data

New table `nar1_client_approvals` (migration 028):

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `nar1_case_id` | FK → `nar1_cases`, cascade |
| `person_id` | FK → `persons` — which director this token was issued to |
| `recipient_email` | the address it was sent to, as sent |
| `token_hash` | **SHA-256 of the token.** The plaintext exists only in that director's mailbox |
| `sent_at` | issue time; the 14-day clock starts here |
| `expires_at` | `sent_at + 14 days` |
| `responded_at` | null until clicked |
| `outcome` | null · `approved` · `superseded` |
| `ip_address` | inet, captured at approval |
| `user_agent` | text, captured at approval |
| `created_at` | |

Index on `token_hash` (unique) and on `nar1_case_id`.

Tokens are 256 bits from `secrets.token_urlsafe`, compared in constant time.
Storing the hash means a database read cannot approve anything.

### The public route, and why it is shaped this way

On the admin API: `GET /public/nar1-approval/{token}` and
`POST /public/nar1-approval/{token}`.

**`GET` mutates nothing.** It renders a static server-side page with a button.
This is the load-bearing decision, not a nicety: Outlook SafeLinks, Gmail, and
essentially every mail-security gateway fetch every link in a message before a
human sees it. A one-click `GET` that approved would be fired by the scanner —
recording the scanner's IP as the approving director, minutes after the email
was sent and before anyone read it. Only the `POST` from that page approves.

Hardening, per the requirement to limit what the route can be made to do:

- Responses are a **fixed set** — approval page, already-approved,
  expired, not-found — and all four are identical in shape, size class and
  timing, so the route cannot be used to discover which tokens or cases exist.
- **Nothing from the request is echoed** into the response. The page renders
  from the case record alone.
- The only accepted `POST` body is empty. There is no field to supply, so
  there is nothing to inject.
- Rate-limited per token and per source IP.
- No session, no cookie, no credential. The token authorises exactly one
  action on exactly one case and nothing else.
- Not registered under the authenticated router; it carries no
  `require_permission` because it has no user, which is precisely why its
  capability is bounded to one row.

### First approval wins

One approval per case. The first valid `POST` records it; every later token
for that case renders "This return has already been approved by {name} on
{date}" and is marked `superseded`. This is the specified behaviour — GSHK
receives one approval, not one per director.

### The link approves; it cannot reject

The page offers one action. A director who disagrees is told to reply to the
email, which is the path the message itself asks for and which staff already
record through `POST /cases/{id}/verification/response`.

This is deliberate. A rejection needs to carry *what is wrong*, and a free-text
box on an unauthenticated public route is the one thing §5's hardening is built
to avoid — it would be the only place in the design where client-supplied text
enters the system without a staff member between it and the case.

### Restarting verification invalidates every outstanding token

When verification is restarted, all `nar1_client_approvals` rows for the case
that have not been responded to are marked `superseded` and stop working.

Without this, a director holding the *previous* email could approve a snapshot
that has since been corrected and re-validated — the portal would record an
approval of a document CR is no longer being asked to file. This is the same
class of defect as the stale-snapshot bug that `filings.supersede()` was
written for, arriving through a different door, and it is why `outcome` carries
a `superseded` value rather than a boolean.

Re-sending verification issues fresh tokens and **restarts the 14-day clock**,
so the deadline printed in the new email is again the one the job reads.

### Auto-approval at 14 days

A **Railway cron service** running `python -m jobs.auto_approve_nar1` at
`0 16 * * *` — 16:00 UTC is 00:00 Hong Kong. It runs against the same image
and environment as the API, so DEV and PROD stay isolated with no extra
credential.

Chosen over an in-process scheduler, which fires once per replica and would
double-approve the moment Railway scales past one instance; and over a GitHub
Actions schedule, which would need a service credential in repo secrets and
fires at whichever URL it is configured with.

The job selects cases where verification was sent, no response was recorded,
`now() > expires_at`, and the case is still awaiting a client decision —
explicitly **excluding** cases already approved or rejected, cases CR already
holds (`CR_FILED_STAGES`), cases completed off-portal (`manual_receipt`), and
tokens marked `superseded` by a verification restart. Approving a return that
has already been filed would put a client decision in the trail *after* the
filing it supposedly authorised.

It approves each as system-originated and writes
`CLIENT_APPROVAL_AUTO_APPROVED`. It is idempotent — a second run the same
night changes nothing — and a failure on one case does not abandon the rest:
each case is committed on its own, and the run reports how many it approved,
skipped and failed.

**Levi must create the cron service in Railway.** Until then nothing
auto-approves; the manual and self-service paths are unaffected.

### Provenance is never lost

Both the signing stage and the audit trail state *how* a case was approved:

- "Approved by {director name} on {date} at {time} HKT" — for a self-approval,
  with the IP available on the audit row.
- "Approved by {director name}, recorded by {staff name}" — for a relayed reply.
- **"System-approved — the client did not respond within 14 days"** — for the
  job.

A bare "Approved" is never rendered. A director who never answered must not
appear to have agreed to anything.

### Audit codes

Seeded by migration with `origin='g_flowdesk'` and an explicit `category` —
the column default is `origin='viewpoint'`, and there is no FK from the audit
rows to the type table, so an unseeded code writes fine and then renders
unlabelled in the trail. That is what migration 022 exists to repair.

| Code | Fires |
|---|---|
| `CLIENT_APPROVAL_LINK_SENT` | Per director, when a token is issued |
| `CLIENT_APPROVAL_SELF_SERVICE` | A director approved through the link; records person, IP, user-agent |
| `CLIENT_APPROVAL_AUTO_APPROVED` | The 14-day job approved the case |

The existing `CLIENT_APPROVAL_RECEIVED` is unchanged and still fires for
staff-relayed replies.

---

## 6 · Pre-submit drift gate

Today `POST /tpsi/filings/{id}/submit` can file a return CR validated weeks
ago against master data that has since been corrected. The client approved one
document; CR would receive another.

In `services/tpsi/filings.py :: submit`, inside the existing gate chain and
**before any CR call or any charge**:

1. Reload the entity graph — `nar1_source.load_entity_graph`.
2. Re-map with the case's stored `signatory_capacity` —
   `nar1_mapper.map_entity`. This is the same pair `prepare` uses, so drift is
   measured against exactly what a fresh preparation would produce.
3. Normalise both documents: strip `ds:Signature`, timestamps and
   presenter-side metadata, canonicalise element order and whitespace.
4. Compare **every field that reaches CR** — company name, BRN, registered
   office, every director and secretary, share capital, shareholdings.

Any difference raises `SubmitGateError` → **409**, audited
`TPSI_SUBMISSION_FAILED` with the differing field names. No CR call, no money.

The refusal **lists each differing field with both values**, at the submit
button:

```
Submission blocked — the validated form no longer matches the company record.

  Director 1 · Residential address
    validated:  Raggatan 9, Stockholm 11859
    current:    Raggatan 14, Stockholm 11859

Restart verification to rebuild and re-validate the return.
```

This is the blocking rule as chosen — any difference in filed particulars —
rendered legibly. A refusal that says only "data differs" leaves the operator
to diff a nine-page statutory form by eye.

`filings.rebuild_draft` and `REBUILDABLE_STAGES` already exist for exactly
this correction, so "restart verification" is a path the code supports.

### The failure mode this must not introduce

The gate sits in front of an irreversible chargeable call. A **false positive**
blocks a legitimate filing near a statutory deadline; a **false negative**
files a wrong return. Normalisation is therefore tested against real
companies through `scripts/nar1_regression.py`: an unmodified case must
produce zero differences across the book. Any noise — element ordering,
whitespace, numeric formatting, absent-vs-empty — is a bug in the comparator,
not something to loosen the rule for.

---

## 7 · User creation without an admin-chosen password

### Backend

`CreateUserRequest` loses `password`. `create_user` generates a
high-entropy password, creates the Supabase Auth user, and sends a welcome
email. `users` gains `must_change_password boolean not null default false`
(migration 029), set true on creation.

`require_user` refuses every route except the set-password endpoint and
`/auth/me` while the flag is set, so the flag cannot be walked around by
navigating directly. Clearing it is the only thing the set-password endpoint
does.

The generated password is **never returned in the API response** and never
logged. The email is the only place it exists.

### Welcome email

Designed with the `frontend-design` skill, under the same constraints as the
client mail: table-based, inline styles, real fallback font stack.

Contents: the recipient's display name, their assigned role, the generated
password, the environment-correct login URL (`admin.g-flowdesk.com` or
`admin-dev.g-flowdesk.com`, derived from `APP_ENV`, never hardcoded), and a
line saying they will be asked to choose their own password on first sign-in.

In non-production this is subject to the `TEST_RECIPIENTS` lock like every
other message — the substitution happens inside `send()`, below every caller,
so no new path can escape it.

### Frontend

`UserManagementPage.jsx` drops the password input entirely — not disabled,
removed — and the form posts three fields. A new set-password screen handles
the first-login redirect.

---

## 8 · Cross-cutting rules

Per `CLAUDE.md`, mandatory on every item here:

- **UAM.** Every new authenticated endpoint carries
  `require_permission(module, permission)`. `manual-receipt` is `tpsi:submit`,
  matching `manual-submit`, because it is evidence for an act that closes a
  case as filed. The public approval route is the sole exception and is
  bounded by token scope instead — §5.
- **Audit.** Every write calls `audit_service.log_event()` before returning
  success. Failures there are swallowed to stderr and never block the primary
  operation. No token, password, or PIN reaches an audit row — the approval
  token is hashed before it is stored and is never logged at all.
- **Tests.** Every route gets a happy path, a 401/403, and an edge case.
  Migration tests are DB-backed and `RUN_DB_TESTS`-gated, following
  `test_migration_016.py`.
- **Migrations.** 028 (approvals + audit codes + `cr_receipt` type), 029
  (`must_change_password`). DEV first, PROD only on explicit sign-off.

---

## 9 · Sequencing

Five blocks. Each is independently reviewable and independently revertable.

| Block | Contents | Depends on |
|---|---|---|
| **A** | §1 fonts · §1b static page set · §3 viewer height | — |
| **B** | §4 receipt upload · §6 drift gate | — |
| **C** | §5 self-approval, table, public route, cron, provenance | — |
| **D** | §2 client email wording | A (§1b page numbering), C (button, deadline) |
| **E** | §7 user creation and welcome email | — |

A, B, C and E are parallelisable. D is last because it is the only piece that
depends on two others.

---

## 10 · Risks

| Risk | Handling |
|---|---|
| A public write route on the API that files statutory documents | GET is inert; fixed response set; no echo; empty POST body; rate-limited; token-scoped to one row (§5) |
| The drift gate blocks a legitimate filing near a deadline | Comparator validated against the real book via `nar1_regression.py`; zero differences required on unmodified cases (§6) |
| A director approves a snapshot that was since corrected, using an old email | Restarting verification supersedes every outstanding token and restarts the clock (§5) |
| Hardcoded page numbers misdirect the client | Resolved: the form is static and §1b restores the full nine-page set, making the sample's references true (§2) |
| Appearance streams regress rendering rather than fix it | Rasterised visual comparison, not only field assertions (§1) |
| Cron double-runs or never runs | Job is idempotent; Railway cron is single-instance by construction; **requires Levi to create the service** (§5) |
| Font licensing | Tinos and Noto Serif TC are both **OFL-1.1** and redistributable; `timesbd.ttf` is Monotype-proprietary and is not shipped. OFL's Reserved Font Name clause is respected: `build_cjk_font.py` instances Noto Serif TC but keeps the upstream family name and the result is embedded in a PDF, never redistributed as a font (§1) |
| Restoring empty pages changes what CR receives | It does not — the filed payload is the XML, unchanged by this. Only the human-readable PDF gains the pages, which is what makes it a facsimile of CR's own output (§1b) |
| `docs/` is gitignored — runtime assets placed there vanish on Railway and CI | Fonts committed beside the module (§1); this spec needs its own `!` allowlist line in `.gitignore` |

---

## 11 · Deployment notes

- `main` auto-deploys to PROD and the live Companies Registry. **Nothing here
  merges to `main` without explicit per-merge consent.** Code approval is not
  release approval.
- Levi must create the Railway cron service before auto-approval does anything.
- Migrations 028 and 029 run on DEV first and on PROD only on sign-off.
- `GET /health` must report the expected environment after each deploy — the
  recipient lock and the login URL in §7 both derive from `APP_ENV`.
