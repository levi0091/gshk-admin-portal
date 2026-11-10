# ND2A and ND2B on G-FlowDesk — build design

**Date:** 2026-09-30
**Author:** Claude (with Levi)
**Status:** Built on branch `worktree-nd2a-nd2b-officer-changes`. Not yet run against CR TEST.
**PRD:** `PRD/Pending/prd-nd2a-nd2b-officer-changes-2026-09-19.md` · **Wireframe:** `Wireframe/admin-portal-nd2/wireframe_v12.html`

> ⚠️ **[INTERNAL]** — @zenexflow.com only.

This document is the PRD plus Levi's seventeen answers of 2026-09-30. Where an
answer reverses the PRD, **the answer wins** and the reversal is recorded in §1.
Everything the build had to assume without being told is in §9.

---

## 1 · What the seventeen answers changed

| # | Levi, 2026-09-30 | What it reverses or settles | Where |
|---|---|---|---|
| 1 | A section on the Natural Person profile to key in a client's e-Registry ID and password | PRD G-2 asked for the ID only and no password | §3, `person_eservice_credentials` |
| 2 | No e-Registry account → wet-ink (manual) workflow only | Removes the per-appointee *Consent route* radio (S-10, AS-31). The route is **derived** | §5 |
| 3, 4, 6 | "Are all the fields really necessary? Always look to simplify." | See §2 — six inputs removed | §2 |
| 5 | No alternate directors | PRD G-1, S-23, A-6/A-16/A-35, `altTo` — out of scope; never offered | §2 |
| 7 | Upload supporting documents per joiner and leaver at the manual checks | Replaces S-14's flat check list | §6 |
| 8 | GSHK sets up the new director's e-Registry account and **stores** its ID and password | Settles PRD Q1/Q2 and **reverses AS-10**: the consent signature is applied by GSHK staff from the stored credential, with no live PIN entry | §5 |
| 9 | After uploading the signed PDF the case must **not** move on by itself | Same rule NAR1 took on 2026-09-14 | §5 |
| 10 | Manual ND2A: no *Download for signing* — the form is prepared on CR's portal | Reverses S-16 / AS-32 | §5 |
| 11, 13 | Submission says the supporting files **will** go to each person's profile; Confirmation shows they **did** | New | §6 |
| 12 | "Paper" submission is really submission through the **CR portal**: type CR's receipt details, as NAR1's manual path does | Reverses S-17b / AS-33 (date · by hand/by post · proof) | §5 |
| 14 | ND2B: the operator does **not** type changes on the workflow. They edit the profile; the case shows a **read-only** card of what changed, asks only for the effective date, and lets a line be omitted | Reverses S-20 and PRD §7.3's "Changes card → profile" direction | §4 |
| 15 | The PDFs must be CR's own ND2A / ND2B, at NAR1's type sizes, with every extra sheet generated | PRD §15.5 | §7 |
| 16 | The profile alert "changed, no ND2B yet" is dismissable | New | §4 |
| 17 | Client Verification first; CR validation needs no PIN; PIN signing only where CR's interface requires it; both e-Sign and wet-ink at submission | Confirms AS-3; narrows signing | §5 |

---

## 2 · Answer to "are all these fields necessary?" (3, 4, 6)

Every input on the three drawers was checked against CR's worksheet
(`tests/fixtures/cr-examples/Worksheet … v1.0.14.xlsx`, sheets `ND2A`/`ND2B`),
CR's fourteen worked examples and the printed forms.

**Removed — the operator is no longer asked**

| Input (wireframe) | Why it can go |
|---|---|
| Capacity → *Alternate Director*, and *Alternate to* | Answer 5. `altTo` is `M=N`; the box prints empty |
| *Already a director or alternate of this company?* (`dirBeforeApptInd`) | Only ever "Yes" when an alternate becomes a director or the reverse. Without alternates it is always **N** for a director and absent for a secretary — derived |
| *Still a director or alternate after this date?* (`dirAfterCesInd`) | Same reasoning — derived, **N** |
| *Consent route: e-Sign / Paper* | Answer 2. Derived from whether the appointee has a stored e-Registry credential |
| Cessation *Note* (free text) | Not on the form and not sent to CR. `resignation_reason` on the tile is written from CR's reason instead |
| The five correspondence-address boxes, **by default** | See below — one tick replaces them |

**Correspondence address vs residential address (answer 4).** They are two
different CR fields and both are required for a director: `indvCorrAddr`
(public, section 3) and `indvResAddr` (PI sheet, never public). They *can*
differ — a director may give the company's office as the public address to keep
their home off the register — so the field cannot be dropped. But for most
appointments they are the same, and NAR1 already files the residential address
in the correspondence slot. So the drawer carries **one tick, on by default:
"Correspondence address is the same as the residential address"**, and the five
boxes (Country/Region among them) appear only when it is unticked. Nothing held
on the Person Profile is ever retyped.

**Kept, because CR requires them and nothing else holds them**

| Drawer | Inputs that remain |
|---|---|
| Add cessation | Officer · Reason (*Resignation/Others* or *Deceased* — CR's `rsnCes`, mandatory for a natural person; pre-set from Date of Death) · Date of cessation |
| Add appointment — natural person | Person · Capacity (*Director* / *Company Secretary*) · Date of appointment · the correspondence tick · for a **secretary only**: the Section 5 "ordinarily resides in Hong Kong" tick (on the printed form; no TPSI field) |
| Add appointment — body corporate | Body corporate · Capacity · Date of appointment · for a **director only**: *Consent signed by* (person + capacity), which CR requires as `associatedPersonId/Name/CapacityDesc` and the printed form requires beside the signature |

Everything else — names, previous names, alias, email, residential address,
identity documents, date of birth, TCSP licence, the body corporate's address,
BR number and email — is **read from the profile and shown read-only**, with a
"missing items" list and a link to the profile.

---

## 3 · Data model (migration 050)

ND2A and ND2B cases are rows in **`nar1_cases`**, distinguished by a new
`form_code`. The table name is a misnomer inherited from Viewpoint; what it
holds is "a case that files one CR form for one company", and every column the
officer-change workflow needs is already there: the client-verification
columns, the approval provenance, the manual signed-form and receipt pointers,
closure, and CR's document status. Reusing it means the approval tokens
(`nar1_client_approvals`), the filing ledger (`tpsi_filings.nar1_case_id`), the
CR status poller and the dashboard view all work unchanged, and there is one
definition of the workflow badge rather than two that can drift.

| Object | What |
|---|---|
| `nar1_cases.form_code` | `'Nar1'` (default, every existing row) · `'Nd2a'` · `'Nd2b'` |
| `nar1_cases.filing_deadline` | Earliest change on the case + 15 days. Stored, because the dashboard sorts and flags on it and PostgREST cannot do either to an expression |
| `nar1_cases.data_checked_at / _by` | The manual route's "Mark as checked", which stands in for CR's validation |
| `nar1_cases.changes_applied_at / changes_undone_at` | When the filed changes were written to the profiles, and when they were taken back |
| `nar1_type` | gains `'change_of_particulars'` (ND2B). ND2A uses the existing `'appointment_and_resignation'` |
| `officer_change_entries` | One row per officer on the form: `kind` (`cessation` / `appointment` / `change`), party, capacity, effective date, CR reason, correspondence address, Section 5 tick, consent signer, KYC tick, the ND2B item list, and what was written to the profile on filing (for undo) |
| `officer_change_documents` | Supporting documents held on the case until it is filed, then pointed at the profile document they became |
| `officer_cr_particulars` | Per appointment: the officer's particulars **as CR holds them**. The baseline ND2B diffs against (§4) |
| `person_eservice_credentials` | A client's e-Registry user ID, the name on that account, and the password, Fernet-encrypted with `TPSI_CRED_KEY`. RLS on, no policy |
| `nar1_case_registry` | Restated: `case_type` comes from `form_code`, `filing_deadline` is appended, and `workflow_overdue` reads the deadline for an officer-change case |
| Permission module | `officer_changes` (`read`, `write`), seeded for every role holding the matching `nar1` level |
| Document types | `nd2a`, `nd2b`, `resignation_letter`, `board_resolution`, `consent_to_act`, `officer_change_support` |

### Permissions (PBI-12)

| Action | Permission |
|---|---|
| Read an officer-change case, its entries, preview, recipients | `officer_changes:read` |
| Open a case; add, edit, remove an entry; send to the client; record the answer; tick KYC; upload supporting documents; upload the signed form; mark as checked; restart; close | `officer_changes:write` |
| Validate with CR; apply signatures | `tpsi:write` |
| File with CR; record a CR-portal filing; upload the CR receipt; undo a profile update | `tpsi:submit` |
| Read whether a person has an e-Registry credential | `persons:read` |
| Store or replace a person's e-Registry credential; dismiss the ND2B alert | `persons:write` |

### Audit events (PBI-11)

Seeded by 050 with `origin='g_flowdesk'`, `category='officer_changes'`:

`OFFICER_CHANGE_ADDED` · `OFFICER_CHANGE_UPDATED` · `OFFICER_CHANGE_REMOVED` ·
`OFFICER_SUPPORT_DOC_UPLOADED` · `OFFICER_SUPPORT_DOC_REMOVED` ·
`OFFICER_CONSENT_SIGNED` · `OFFICER_SIGNED_FORM_UPLOADED` ·
`OFFICER_FILING_RECORDED` · `OFFICER_CHANGES_APPLIED` · `OFFICER_CHANGES_UNDONE` ·
`OFFICER_PARTICULARS_DISMISSED` · `PERSON_ESERVICE_CRED_SET`

Reused unchanged: `CASE_STATUS_CHANGED`, `CASE_FIELD_UPDATED`, `EMAIL_SENT`,
`CLIENT_APPROVAL_LINK_SENT`, `CLIENT_APPROVAL_RECEIVED`,
`CLIENT_APPROVAL_SELF_SERVICE`, `TPSI_SUBMISSION_ATTEMPTED/SUCCESS/FAILED`,
`NAR1_CASE_CLOSED`, `TPSI_DOC_STATUS_CHECKED`, `NAR1_CR_STATUS_CHANGED`.

`PERSON_ESERVICE_CRED_SET` never carries the password, its length or a hint.

---

## 4 · ND2B — changes come from the profile (answers 14, 16)

**The operator never types a changed value on the case.** They edit the Person
Profile (or, for a body corporate officer, the company profile). The case then
shows what differs from what CR holds.

**"What CR holds" is `officer_cr_particulars`** — one row per appointment
(company × officer), holding name, alias, email, residential address,
correspondence address, identity documents and TCSP details.

- It is **captured the first time a tracked field is about to change**, from
  the values as they stand before the edit, for every current appointment of
  that person. A person nobody has edited has no baseline and therefore no
  pending change — which is the honest answer for 7,000 rows that came out of
  Viewpoint.
- **Pending changes** for an appointment = baseline ≠ profile now, item by
  item, in CR's own items: (a) Chinese name, (b) English name, (c) alias,
  (d) residential address — directors only, (e) correspondence address,
  (f) email, (g) HKID, (h) passport, (i) TCSP licence — secretaries only.
- **Changing a value back makes the change disappear**, because there is
  nothing left to differ.
- **Dismissing the alert** on the Person Profile sets the baseline to the
  current values for all of that person's appointments — "this was data
  loading, not a real-world change". Audited.
- **Filing an ND2B** moves the baseline forward **only for the items that were
  filed**. A line the operator omitted is still pending afterwards, which is
  correct: CR has not been told.
- A residential address change on a director whose correspondence address *is*
  their residential address (the common case) is **two** items, (d) and (e) —
  CR holds the old address in both places.

On the case, each officer added is a read-only card listing only the changed
items, old value → new value. The operator supplies **the effective date** of
each and may **omit** a line (confirmation pop-up). Nothing else is editable.
The profile is *already* right, so filing an ND2B writes nothing to it; it moves
the baseline.

Part A of the form ("particulars currently registered") is printed from the
**baseline**, not from the profile — a renamed director is identified to CR by
the name CR knows.

---

## 5 · The six stages (answers 2, 8, 9, 10, 12, 17)

Same page, stepper and badges as NAR1. `services/nar1_case_status` decides the
badge for all three forms.

| # | Stage | What happens |
|---|---|---|
| 1 | **Client Verification** | Changes card (ND2A: Leaving / Joining; ND2B: officers and their changed items). Company rules checked live. The draft — CR's own form, **public pages only** — is previewed and emailed with a Confirm button. Reply-by date defaults to 5 days before the deadline, never less than 2 days out. **No auto-approval** |
| 2 | **Data Verification** | Per joiner and leaver: KYC tick (joiners) and supporting-document uploads. Signing capacity. Then **Validate with CR Portal** (free, no PIN) on the e-Sign route, or **Mark as checked** on the manual route |
| 3 | **Signing** | *e-Sign:* one button. The portal applies a consent signature for each new director from that director's **stored** e-Registry credential, then the overall signature from the signed-in user's own, in one `verifyPinSigning` call. *Manual:* upload the signed PDF prepared on CR's portal; then a deliberate **Continue to Submission →** |
| 4 | **Submission** | Lists what will be written to the profiles **and which supporting files will be saved to which profile**. *e-Sign:* two-step confirm → `submitFormNd2a/Nd2b`. *Manual:* type CR's receipt details and attach CR's receipt, behind the same `tpsi:submit` gate |
| 5 | **Confirmation** | Receipt; *Profile updated* list; *Supporting documents saved* list with links |
| 6 | **CR Status** | The existing poller and *Check now*. On a rejection: **Undo profile update** |

**The route is derived, not chosen.** An ND2A needs a consent signature for each
newly appointed **director** — CR's interface requires it (`selectPersonId`
inside the appointment and a `PinSign` over it) — and for nothing else:
cessations, secretary appointments and every ND2B carry only the overall
signature. So:

- e-Sign is available when every new director (or, for a body corporate
  director, the person signing for it) has a stored e-Registry ID, name and
  password.
- Otherwise the case is **manual only**, and the screen names who is missing a
  credential.
- The operator may always choose manual.

The overall signature is NAR1's: the signed-in user's own e-Service account,
signing for the body corporate secretary in the capacity chosen at Data
Verification. **No officer's e-Registry account is used for anything except
their own consent.**

**Manual route.** No CR call is made at any stage. There is no ND2A download
button (answer 10) — the operator prepares and downloads the form on CR's
portal. The ND2B manual route keeps the download, since nothing was said about
it and the form is otherwise identical work.

---

## 6 · Supporting documents (answers 7, 11, 13)

At Data Verification each joiner and leaver has an upload area: *Resignation
letter*, *Board resolution*, *Consent to act*, *Other*. Files are stored under
the case (`officer-change/{case}/{entry}/…`) and **are not yet on anybody's
profile**.

When the form is filed — CR accepted the e-filing, or the CR-portal filing was
recorded — each file becomes a document on the **officer's own profile**
(person, or the body corporate's company record) through
`document_service.upload_document`, so it is versioned and audited like any
other. The case keeps the pointer.

Submission states this in the future tense ("will be saved to"), Confirmation
in the past ("saved to", with links). The signed form and CR's receipt stay
with the **company** and the **case** respectively, as NAR1's do.

---

## 7 · The PDFs (answer 15)

`services/officer_change_form/` fills CR's own `ND2A_fillable.pdf` and
`ND2B_fillable.pdf` (Specification No. 1/2023), committed beside the code as
runtime assets. It reuses `nar1_form.appearance.bake`, so the output is flat,
drawn in the embedded Tinos / Noto Serif faces, and carries no form field.

**Type sizes are NAR1's**, which were measured off a filed return: 10pt bold for
every value, 14pt for the BR number in each page header, 12pt for the company
name, the presenter's block in the regular face. Left-aligned 9.4pt inside the
box; centred only for the header BRN, the company name, date cells, identity
numbers and page counts.

**Every sheet the form needs is generated.**

| Form | Always | Added when |
|---|---|---|
| ND2A | pages 1–3 | Continuation Sheet A per cessation after the first · B per natural-person appointment after the first · C per body-corporate appointment after the first · one PI-ND2A per natural person appointed (omitted for a secretary with neither HKID nor passport) |
| ND2B | pages 1–3 | Continuation Sheet A per natural person after the first · B per body corporate after the first · one PI-ND2B per natural person whose ID number or residential address changed |

Page 3 states the number of each sheet attached. `_assert_nothing_dropped`
re-counts the output against the entries before any bytes are returned.

**Two renderings.** `public_only=True` drops the PI sheets and is what the
client is emailed; the count boxes on page 3 still state how many PI sheets the
filed form carries. The full rendering is for staff.

**Partial and full identity numbers.** Public pages print the partial number by
CR's rule (note 10 on the form); the PI sheet prints the full number and the
HKID check digit in its own box.

The signature Date is CR's filing date and is empty until there is one, as on
NAR1.

---

## 8 · CR's XML

`services/officer_changes/nd2a_mapper.py` and `nd2b_mapper.py` are pure: entries
and profile graph in, CR dict out, every problem reported at once as a
`MappingError`. `form_xml.py` emits elements in CR's worksheet order.

- Dates `DD/MM/YYYY`. Addresses through `nar1_mapper._address`, so the Hong Kong
  district code and CR's country code rules are the ones NAR1 proved live.
- **Cessation and ND2B Part A:** partial identity numbers. **Appointment and
  ND2B new ID:** the full number with the HKID check digit split out.
- A director appointment carries `id="S<n>"` on its bean, the appointee's
  `selectPersonId`/`selectPersonName`, and `dirBeforeApptInd`. A body corporate
  director carries `associatedPerson*` and `selectAssoBrNo`.
- The form-level signatory block is `nar1_mapper._signatory_block`, unchanged —
  the body-corporate scheme CR's live register verified on 2026-09-16.
- Consent signatures: `<cr:PinSign URI="#S1">` inside `<cr:formDataSignatures>`,
  digest over the bean as an `XMLSerializer` emits it, then the overall
  signature over the whole `EForm`, last. This follows CR's reference program
  (`createEFormSignatureV2`, the non-`FormSigner` branch).

CR's fourteen worked examples are fixtures; the mappers are tested against them
element for element.

---

## 9 · Assumptions made without asking

| # | Assumption |
|---|---|
| B-1 | ND2A/ND2B cases live in `nar1_cases` (§3). The PRD recommended this (§15.1) |
| B-2 | "The 2 files" in answer 11 are the supporting documents of answer 7. They go to each **officer's** profile; the signed form goes to the company, CR's receipt to the case |
| B-3 | Answer 10 removes the download button on the **ND2A** manual route only |
| B-4 | The manual CR receipt is: CR case number and transaction date (required), transaction time and CR document reference (optional), plus the uploaded receipt. No payment fields — ND2A/ND2B are free |
| B-5 | Profile changes are written when the form is **filed**, not when CR registers it (PRD Q10's proposal) |
| B-6 | ND2A recipients: every current director and every incoming director with an email. ND2B: the officer concerned (PRD Q3/Q4 proposals) |
| B-7 | The copy and reply-to mailbox is `renewal@getstarted.hk`, as NAR1 (PRD Q24 open) |
| B-8 | Reply-by = deadline − 5 days, never less than today + 2 (PRD AS-5); the operator may change it |
| B-9 | A person's e-Registry password is stored encrypted with the key that protects staff CR credentials and is never returned by any endpoint — not even as the masked last-four hint a staff member sees for their **own** CR password. That hint is defensible because it is scoped to its owner; a client's password shown to every holder of `persons:read` is not. The screen says only whether one is stored |
| B-16 | A body corporate with more than 200 current appointments (in practice GSHK Ltd, secretary of 5,603 companies) gets no ND2B baseline and therefore no alert when its particulars are edited. One ND2B per company for the firm's own change of address is the bulk case §10 leaves out |
| B-10 | ND2B tracks changes from the first edit after this release. Edits made before it have no baseline and raise no alert |
| B-11 | Dismissing the alert dismisses it for all of that person's appointments |
| B-12 | One open ND2A per company that has not been sent to the client: *Report a change* adds to it. Same for ND2B |
| B-13 | When GSHK Ltd is itself the secretary ceasing or being appointed, the overall e-signature may be refused by CR (PRD Q7/Q8). The manual route is the fallback; nothing special-cases it |
| B-14 | The email wording is a draft in the NAR1 letter's structure (PRD Q14). It never prints a full ID number or a home address |
| B-15 | The per-appointment correspondence address is set by the ND2A appointment. A later change to it alone has no editor yet; a residential change carries it along (§4) |
| B-17 | A body-corporate appointee is sent with its names, registered address **and** `corpBrNo` when it has one. CR's examples split "CR-registered (BR number only)" from "BR-registered (names only)"; sending both is the reading that cannot omit something CR needs. If CR TEST refuses the extra elements, drop the names when `corpBrNo` is present |
| B-18 | A secretary held only on the secretary register (`company_secretaries`, the register the NAR1 mapper reads first) is on the ND2A board, so "keeps a company secretary" holds for those companies. An entry naming one **mirrors it into an `entity_officers` row** — same person, or the one live company of that name, same appointment date — because every later step keys on an officer row; the audit row names the promotion. A register name matching no company, or two, is refused by name rather than guessed |

## 10 · Not built

Alternate directors (answer 5). The NAR1 warning for an open officer change
(S-22) and the "open ND2Bs" prompt after adding an identity document (S-21
banner) — the dismissable alert covers the same ground from the profile. ND4,
ND5, ND7. A bulk ND2B for GSHK Ltd's own particulars (PRD Q17). Filing in
Chinese.

## 11 · Verified on CR TEST, and what still is not

**2026-10-02, 14:49–15:00 HKT, apitest.cr.gov.hk** — every form built by OUR
mapper (`map_case(..., for_esign=True)` → `form_xml.build`), re-pointed at CR
TEST's own register (company T0001137 and its associated test accounts, from
CR's test-account workbook) because CR checks every signer and officer against
that register. `validateForm` and `verifyPinSigning` only; **nothing was
submitted**.

| Check | Result |
|---|---|
| PRD SC-5: all 14 CR examples validate | **14/14 validated** |
| All 14 signed (`verifyPinSigning`) | **14/14 "Pin Signature(s) Verified Successfully."** |
| Consent signature, individual director (`PinSign URI="#S1"`) | verified |
| Consent signature, body-corporate director (associated person signs) | verified |
| One ND2A with 2 cessations + 2 appointments, consents S1 **and** S2 | validated and signed |
| B-13: body-corporate secretary signing, a natural person signing for it (GSHK's case) | validated and signed, with and without a consent |
| B-17: corporate appointee sent with names **and** BR number | accepted (4 cases) |

What CR TEST taught, now in the code (`officer_change_filing._CR_HINTS`):

- **CR matches a ceasing or changing officer against its register** by name and
  partial identity number — "No matched individual officier." (CR's spelling).
  This is why a cessation names the officer from the ND2B baseline.
- **PRD R-3 is a real constraint, not a formatting one.** An appointee sent with
  no Chinese name, when their e-Registry account holds one, is refused at
  VALIDATION: "signer does not match with officer." CR compares the appointee's
  particulars with the consent signer's account. A director with genuinely no
  Chinese name on their account was not testable (every CR test account has one).
- CR's sample signer ids are refused ("Please check selectPersonId field."):
  the signer must be a real account associated with the company.

**One filing submitted, approved by Levi (2026-10-02, ~15:05 HKT).** An ND2B
changing ONLY the test Director's email on T0001137 (effective 01/10/2026),
signed by the test Secretary: validated, signed, `submitForm` once. CR TEST
receipt: case **141946253**, document **ND2B (T0022892651)**. `docStatusEnquiry`
by that case number listed it **immediately** as `Lodged` ("(E)FND2B - Notice of
Change in Particulars of Company Secretary and Director") — on TEST, unlike the
same-day silence measured on PROD for NAR1.

**A free form's receipt has no payment block:** `refNo`, `transactionDate`,
`transactionTime` and `totalAmount` all come back empty, and the document
reference is only in `docCodesWithBarcode`. `signing.with_document_ref` lifts it
into `documentRefNo`, and Confirmation shows the portal's own filing time.

Still not verified: the two PostgREST queries noted in the final review (the
auto-approval job's inner join, the register name match), which need DEV.
