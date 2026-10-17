# ND2A / ND2B — Jacqueline's feedback of 1 October 2026

> **Revised by `2026-10-05-nd2-levi-revisions-design.md`** (Levi, 4–5 October): §2.2's in-portal consent, §2.3's toggle and standard wording, §2.4's resolution and consent checks and §2.14's per-company dismissal no longer stand as written here.

**Date:** 2026-10-02
**Author:** Claude (Levi asked for build without check-ins; every decision taken alone is in §5)
**Status:** Built on `nd2a_nd2b` (commits from `26647d8`), not pushed. Migration 052 not applied to DEV or PROD. HKID NIL (C-10) not yet run on CR TEST.
**Builds on:** `2026-09-30-nd2a-nd2b-officer-changes-design.md` (the ND2A/ND2B build, branch `nd2a_nd2b`)
**Source:** `nd2a.pdf`, pages 24–34 only — "Related to ND2A" and "Related to ND2B", comments and questions by Jacqueline (GSHK), with Brian's notes. Pages outside 24–34 were deliberately not read (Levi, 2026-10-02).

> ⚠️ **[INTERNAL]** — @zenexflow.com only.

---

## 1 · What was asked, and what this build does

### ND2A — comments 1–10

| # | Jacqueline / Brian | Decision |
|---|---|---|
| A1 | Clients let GSHK fill in the most recent date; the effective date should be **optional** when the draft goes to the client, and entered on the **Signing — e-Sign** and **Signing — Paper** pages before the signature | §2.1 — effective dates may be blank at send. The email and PDF say "a date to be confirmed". A blank date is **deferred** and is entered at Signing on both routes; nothing is signed or filed without it |
| A2 | A new director must sign the **Consent to Act** (page 2) before filing; "can they sign directly from the system?" | §2.2 — when GSHK holds no e-Registry account for the new director, their verification email carries a second button, **Sign consent to act**, to a no-script page where they type their name and tick the statement. The portal stamps their signature onto their own consent page of the ND2A and files it as the entry's *Consent to act* |
| A3 | Every change of director or secretary needs a **written resolution**; send it with the ND2A in one email — upload it, or build it in the system | §2.3 — both. Any document can be uploaded to the case and ticked **Send with the email**; and the portal generates a draft **Written Resolutions of the Directors** from the change list, previewable and attachable with one tick. One email carries the draft form and every attachment |
| A4 | Change the Client Verification email + Confirm page, and the **manual checks** (resignation letter and board resolution as checks with an attachment) | §2.4 — Data Verification's per-officer list becomes a **Manual checks** list: KYC per joiner, resignation letter per leaver, signed written resolution per case, consent to act per new director on the manual route. Each document check ticks itself when its file is attached. Leaving Data Verification requires every check |
| A5 | GSHK opens the director's e-Registry account and completes the e-PIN, so the client does no e-signature, and the account details are never disclosed | §2.2 — on the e-Sign route the consent is applied by GSHK staff from the stored account (unchanged mechanism); the screen copy that offered "option A — the director types it through a one-time link" is removed, and nothing the client sees mentions the account |
| A6 | The rules box need not be shown in full; keep three lines | §2.5 — "After these changes the company will have N directors (…) and M secretary" · "Directors: X and Y" · "A company secretary remains — Z". A breach is always shown; everything else is behind *Show all checks* |
| A7 | When no director would remain, offer a button so the case is **closed pending further instructions**; GSHK does not file ND4 for the client | §2.5 — the breach panel carries **Close case — pending further instructions**, which opens the permanent close with that reason pre-filled, and a note that the client may file ND4 themselves |
| A8 | The **PI page** must be sent to the client too (ND2A and ND2B) | §2.6 — the client's draft is CR's full form, PI sheets included; the email and the screen say so |
| A9 | HKID is filed as **"NIL"** when the director does not use an HKID | §2.7 — a passport-only appointee is sent with `indvHkidNo = NIL` (CR's worksheet marks the field mandatory) and the printed HKID box reads NIL, on the draft and the PI sheet |
| A10 | e-Reg cannot take a corporate director's consent — **except for Hong Kong companies** (Brian) | §2.8 — e-Sign is offered for a body-corporate director only when it is a Hong Kong company; otherwise the case is manual-only and the reason names the company and its country |

### ND2A — questions 1–6 (answered in §4; two of them change code)

| # | Question | Code change |
|---|---|---|
| AQ1 | Will one automated email carry all related forms? | Partly — any related document can be attached (A3). Separate forms keep separate emails (§4) |
| AQ2 | Client declines a change already shown on the draft NAR1 — how do we send a NAR1 without it? | None (§4) |
| AQ3 | Is there an alert, when submitting to CR, that another ND2A/NAR1 case is open? | **Yes, built** — §2.9 |
| AQ4 | How fast are we told CR rejected a filing? | None (§4) |
| AQ5 | Can a different correspondence address be changed from the drawer, or only from the client's folder? | **Built** — §2.10: per-appointment correspondence address on the Person Profile |
| AQ6 | Is the e-Reg ID typed in by hand? Is the system linked to CR? We send drafts before the e-Reg account exists | Copy only — §2.2 (the consent line on the change list says whether an account is on file) |

### ND2B — comments 1–4

| # | Jacqueline | Decision |
|---|---|---|
| B1 | ND2B effective date normally **defaults to the anniversary date**, so ND2B and NAR1 agree and are filed together | §2.11 — a new ND2B line is dated the return date of the company's open NAR1, else its latest anniversary if that is within the last 42 days; otherwise left blank |
| B2 | PI pages must be shown to the client | Same as A8 |
| B3 | List addresses in CR's format template | §2.12 — every address the officer-change screens and the profile show uses CR's five labelled lines: *Flat/Floor/Block etc.* · *Building (Name)* · *Street/Estate/Lot/Village etc.* · *District/City/Province/State/Postal Code etc.* · *Country/Region*, with "(blank)" for an empty line in a before/after comparison |
| B4 | The individual profile does not show correspondence and residential address separately | §2.10 |

### ND2B — questions 1–3 and note 1

| # | Question / note | Code change |
|---|---|---|
| BQ1 | Can NAR1 and ND2B be filed together? An alert for a pending case? "We usually submit the ND2B even if the client has not confirmed" | §2.9 (alert) and §2.13 — **Proceed without client confirmation** on an ND2B, with a required reason, audited; the ND2B email says GSHK will proceed by the deadline |
| BQ2 | Clients may keep different passport/address details per company — does an ND2B apply only to the companies ticked? | §2.14 — yes (unchanged), and the pending-change alert can now be dismissed **for one company** |
| BQ3 | The email template may need GSHK's usual wording | None — awaiting GSHK's template (§4) |
| N1 | e-Reg and CR data do not sync; an e-Reg account opened with an old passport fails later. Can the system tell? | §2.15 — the e-Registry card records the identity document the account was opened with, and the portal warns when the profile now holds a different one |

---

## 2 · Design

### 2.1 Deferred effective dates (A1)

* **Entries.** `effective_date` is optional on a cessation, an appointment and an ND2B item. `rules.evaluate` reports a missing date as a **notice**, not a rule: it no longer blocks sending.
* **At send** every undated entry and ND2B item is marked **deferred** (`officer_change_entries.date_deferred`, and `deferred: true` inside an ND2B item). The mapper leaves the date out of the client's draft; the PDF's date boxes print empty; the email says "with effect from a date to be confirmed when we file this notice".
* **After send** only a deferred date may be set, through `PUT /officer-changes/{id}/entries/{entry_id}/effective-date` (`officer_changes:write`). It refuses a date after today, refuses once the form is signed (e-Sign) or the signed form is uploaded (manual), and supersedes a CR-validated filing, since CR's answer described an undated form. Audited as `CASE_FIELD_UPDATED` (`field: effective_date`). A date the client saw cannot be changed this way: that is still a restart.
* **Where the operator meets it.** An **Effective dates** panel lists every deferred change with a date input:
  * *Signing — Paper*: above the upload. The signed form cannot be uploaded and the filing cannot be recorded while a date is missing.
  * *Signing — e-Sign*: CR's validation checks the dates, so with a deferred date Data Verification ends with **Continue to Signing** (it records the manual checks, `data_checked_at`, without calling CR), and Signing runs **Validate with CR** and then **Apply signatures**. When every date is present, the existing flow is unchanged: validate at Data Verification.
* **Deadline and reply-by.** The filing deadline is computed from the dated changes. With none dated, reply-by defaults to today + 5 days.

### 2.2 Consent to act (A2, A5, AQ6)

Every new **director** needs a consent to act. Which mechanism applies is decided **per director at send time**:

| The director's position | What happens |
|---|---|
| GSHK holds their complete e-Registry account (natural person), or the body corporate is a HK company whose signer has one | e-Sign: GSHK applies the consent from the stored account at Signing (unchanged). The director's email says: *"No signature is needed from you. We will apply your consent to act through the e-Registry account we set up with you."* |
| No stored account, natural person, with an email address | **e-consent**: their email carries **Sign consent to act**. The page shows the company, the capacity, CR's statement *"I consent to act as director of this company and confirm that I have attained the age of 18 years."*, and asks for the full name exactly as on the form plus a tick. On submit the portal renders the ND2A sent to the client, takes the page carrying that director's consent box, stamps their typed name and a line *"Signed electronically via G-FlowDesk · DD Mon YYYY HH:MM HKT"* into the "Signed:" box, appends a one-page signature record (name typed, time, IP address, browser, case and revision), and files it as the entry's *Consent to act* document |
| No stored account and no email, or a body-corporate director | The consent is collected on paper and uploaded at Data Verification (manual check) |

* **Tokens.** `officer_change_consents` (one row per new natural-person director per send): token hash only, revision, expiry (= the reply-by date, 23:59:59 HKT), superseded at the next send or a restart. The consent link is separate from the Confirm link because the first director to Confirm supersedes every other Confirm link on the case, and the incoming director must still be able to sign afterwards.
* **The page** obeys every rule of the Confirm page: GET writes nothing, no script, `no-store`, one "no longer available" answer for every miss, rate-limited. The POST takes two fields, the typed name and the tick. The name must match the name on the form (case and spacing ignored), and if it does not, the page says so and keeps the case unchanged.
* **Audit.** `OFFICER_ECONSENT_LINK_SENT` per link, `OFFICER_ECONSENT_SIGNED` with IP and user agent.
* **Legal standing** is stated, not assumed: the screen calls it "signed electronically in G-FlowDesk". Whether CR accepts it on a paper filing is GSHK's call (§5, C-6). On e-Sign, CR's own consent signature is still applied from the e-Registry account.
* **The change list's consent line** says which mechanism applies: *"Consent: e-Sign — e-Registry account on file"*, *"Consent: signs in G-FlowDesk from their email (no e-Registry account yet)"*, *"Consent: on paper — not a Hong Kong company"*. The Data Verification copy that referred to "option A / option B" is gone.

### 2.3 Written resolution and other attachments (A3, AQ1)

* `officer_change_documents.entry_id` becomes nullable: a **case-level** document belongs to the form, not to one officer. When the form is filed it goes to the **company's** profile.
* Any case document can be marked **Send with the email** (`send_with_email`). Client Verification gets an **Attachments** card: upload (type: written resolution or other), tick to send, remove before sending.
* **Generated written resolution** (ND2A only): `services/officer_changes/resolution.py` builds *"Written Resolutions of the Directors of {COMPANY} passed pursuant to the Articles of Association"* from the change list: one resolution per cessation (accepting a resignation, or noting a death), one per appointment, and one authorising any director or the company secretary to sign and deliver Form ND2A and update the statutory registers. It has a signature block for each director in office before the changes, excluding a director recorded as deceased, and leaves the date lines blank. **Preview** and **Attach to the email** (`nar1_cases.attach_resolution`). A blank effective date reads "with effect from the date of this resolution".
* The email lists every attachment by name under "Attached:".

### 2.4 Manual checks (A4)

`services/officer_changes/checks.py` derives the list from the entries, the case documents and the chosen route. Nothing is stored that the documents and ticks do not already say:

| Check | For | Satisfied by |
|---|---|---|
| KYC / WorldCheck cleared — *name* | each appointment | the existing KYC tick |
| Resignation letter on file — *name* | each cessation not by death | a `resignation_letter` document on that entry |
| Signed written resolution on file | the case (ND2A) | a `board_resolution` document on the case or any entry |
| Consent to act signed — *name* | each new director, **manual route only** | an e-consent, or a `consent_to_act` document on that entry |

`POST /validate` and `POST /mark-checked` refuse with 409 `checks_incomplete`, naming what is missing. The Data Verification card follows Jacqueline's mock-up: one row per check, ticked green when done, with the attached file's name, date and **Replace**. ND2B has KYC-free changes and no resolution, so its list is empty and nothing is gated.

### 2.5 The rules box (A6, A7)

`rules.evaluate` adds `board: {directors: [{name, party_type}], secretaries: [{name, new}]}` and `lines: [three strings]`. The card shows the three lines. A failing rule is always listed, and the rest sit behind **Show all checks (n)**. When the board would have **no director at all**, the blocked-send area shows **Close case — pending further instructions**, which opens the existing permanent close (`CloseCaseModal` gains `initialReason`) pre-filled with *"Pending further instructions — no director would remain after these changes. The client has been told they may file Form ND4 themselves."*. A note above it says GSHK does not file ND4 on the client's behalf.

### 2.6 PI sheets go to the client (A8, B2)

The emailed draft and the screen preview are the **full** form, PI sheets included (`audience=client` now renders it; `audience=public` keeps the public-only rendering for anyone who needs it). The email says: *"The draft includes the protected-information sheet(s) — full identity numbers and residential addresses — for you to check. They are filed with the Companies Registry but are not open to public inspection; please keep this email private."* The email **body** still never prints a full identity number or a home address (spec B-14).

### 2.7 HKID "NIL" (A9)

`nd2a_mapper.full_ids`: a person with a passport and no HKID is sent `indvHkidNo = NIL` (no check digit) beside the passport. With neither document, both fields are NIL (unchanged). The printed HKID box, on the public page and on the PI sheet, reads **NIL** where it used to print a dash. ND2B already sends NIL for a removed HKID, and its PI sheet now prints NIL there too.

### 2.8 Corporate directors and e-Reg (A10)

`prepare.consent_plan` refuses e-Sign for a body-corporate director unless the body corporate is a Hong Kong company. That means `incorporation_place` resolves to HK; with no incorporation place recorded, a CR number counts as HK. The reason reads: *"e-Registry accepts a body-corporate director's consent only for a Hong Kong company — {name} is incorporated in {country}. File this ND2A on the manual route."* Because the e-Sign route is derived from the consent plan, the case becomes manual-only.

### 2.9 Other open cases (AQ3, BQ1)

`nar1_cases.other_open_cases(entity_id, exclude=case_id)` lists the company's other cases that are neither closed nor filed: `{id, case_no, case_type, workflow_status}`. Both composites carry it as `other_open_cases`. The **Submission** stage of NAR1 and of ND2A/ND2B opens with an alert: *"This company also has ND2B-2026-0003 open (Awaiting client). If this filing should reflect it, or be filed with it, deal with it first."*, linking each case. ND2B's Client Verification names an open NAR1 beside the anniversary default (§2.11).

### 2.10 Correspondence address per appointment (AQ5, B4)

* The person's **Residential Address** gets a heading in read-only view; it had one only while editing, which is why Jacqueline could not tell which address she was looking at.
* A new **Correspondence Address** card lists each current directorship and secretaryship: *"Same as residential address"* or the address in CR's five lines, with **Edit** (`persons:write`). Edit writes `entity_officers.correspondence_address_id` through `PUT /persons/{id}/appointments/{officer_id}/correspondence-address` (an address, or `{"same_as_residential": true}`), capturing the ND2B baseline for **that appointment** first.
* `particulars` diffs each appointment against its own correspondence address. An explicit correspondence address is no longer "never reported", because something now edits it. A change raises an ND2B item (e) **for that company only**.
* Filing an ND2A appointment with a different correspondence address now writes `correspondence_address_id` on the new officer row, so the profile and CR agree.
* So the answer to AQ5: before the form is sent, **Edit** the appointment on the case. After filing, change it on the Person Profile under that company, which raises an ND2B for that company alone.

### 2.11 ND2B defaults to the anniversary (B1)

`deadlines.anniversary_default(entity, open_nar1)`: the open NAR1 case's return date if the company has one, otherwise the most recent incorporation anniversary on or before today if it is no more than 42 days ago, otherwise none. A new ND2B line gets that date, and the operator can change it. The card says *"Dated the anniversary, 12 Mar 2026, so this ND2B matches the NAR1 made up to that date."*.

### 2.12 CR's address format (B3)

`frontend/src/lib/crAddress.js` exports the five labels and a `crAddressLines(address)` helper. The district line joins city, region and postcode, as `nar1_mapper._address` does, and the country shows its name. Used by `AddressBlock` (read-only and edit labels), the ND2B card's before/after (one line per label, "(blank)" where empty) and the new correspondence card. The backend `particulars.describe` keeps its one-line form for the email.

### 2.13 ND2B — proceed without client confirmation (BQ1)

`POST /officer-changes/{id}/verification/proceed` (`officer_changes:write`, **ND2B only**, after send, before any answer). It takes a required `reason` and sets `client_approved = true` with `client_approval_source = 'staff_waiver'`. It does **not** revoke the client's link: a client who confirms later replaces the waiver with their own confirmation, and the public page does not tell them it is "already confirmed". Audited as `OFFICER_CONFIRMATION_WAIVED`. The ND2B email adds: *"If we do not hear from you by {date}, we will proceed with filing so that the Companies Registry receives this notice within the 15-day period."*. ND2A is unchanged: never filed without a confirmation.

### 2.14 Dismiss for one company (BQ2)

`POST /persons/{id}/particulars-changes/dismiss` and the company equivalent accept an optional `entity_id`. With it, only that appointment's baseline moves. The alert offers **Not for this company** on each row beside the existing dismiss-all. Audited as `OFFICER_PARTICULARS_DISMISSED` with the company named.

### 2.15 e-Registry identity document (N1)

`person_eservice_credentials` gains `registered_id_type` (`hkid` | `passport`) and `registered_id_number`, both optional, entered on the e-Registry card as *"Identity document this account was opened with"*. The metadata reports `registered_id_mismatch` when the profile no longer holds that number. The card, Data Verification and Signing then warn: *"{name}'s e-Registry account was opened with passport X123…; the profile now holds Y456…. CR does not update e-Registry when the register changes, and compares them when the consent is signed. Update the e-Registry account first."* (partial numbers on the case screens). CR's refusal hint for "signer does not match with officer" gains the same cause.

---

## 3 · Data, permissions, audit

**Migration 052** (revises 050):

| Object | Change |
|---|---|
| `officer_change_entries.date_deferred` | boolean, default false |
| `officer_change_documents.entry_id` | nullable (case-level documents) |
| `officer_change_documents.send_with_email` | boolean, default false |
| `officer_change_documents.source` | `upload` (default) · `econsent` · `generated` |
| `officer_change_documents.uploaded_by_name` | text, for an e-consent (no portal user) |
| `nar1_cases.attach_resolution` | boolean, default false |
| `officer_change_consents` | new: case, entry, person, token_hash (unique), revision, expires_at, superseded_at, signed_at, signed_name, ip_address, user_agent, document_id. RLS on, no policy, revoked from `anon`/`authenticated` |
| `person_eservice_credentials` | `registered_id_type`, `registered_id_number` |
| `audit_event_types` | `OFFICER_ECONSENT_LINK_SENT`, `OFFICER_ECONSENT_SIGNED`, `OFFICER_CONFIRMATION_WAIVED` (origin `g_flowdesk`, category `officer_changes`) |

Reversible. The downgrade refuses while case-level documents or consent rows exist, rather than drop them.

**Permissions.** No new module. Officer-change routes take `officer_changes:read/write` as before. The correspondence-address and per-company dismiss routes take `persons:write` (the company dismiss takes `companies:write`). The public consent page is unauthenticated, by token, like the Confirm page.

**New audit types:** the three above. Everything else reuses `CASE_FIELD_UPDATED`, `OFFICER_SUPPORT_DOC_UPLOADED/REMOVED`, `DOCUMENT_GENERATED`, `EMAIL_SENT`, `OFFICER_PARTICULARS_DISMISSED`, `PERSON_ESERVICE_CRED_SET` (never the ID number).

**Tests:** pytest for every service and route above (happy path, 401/403, edge cases, the public page's no-script and GET-writes-nothing rules), Vitest for every changed component.

---

## 4 · Answers to the questions (for Levi to relay)

* **AQ1 — one email for several forms?** Each form still gets its own email and its own Confirm link. A NAR1 and an ND2A are approved and filed separately, and a revision of one must not kill the other's link. What this build adds is attachments: the written resolution, and any other document (for example the NAR1 draft), can go with the ND2A in that one email.
* **AQ2 — client declines a change already on the draft NAR1.** For an ND2A, the change reaches the profile only when the ND2A is filed, so a NAR1 built before then does not carry it. For an ND2B, the profile is edited first. If the client declines, edit the profile back: the ND2B line disappears and the alert clears. Then **Restart verification** on the NAR1, and the client receives *[Rev. 2]* without the change, while the Rev. 1 Confirm link stops working.
* **AQ3 — alert for an open case at submission?** Yes, built (§2.9), on both NAR1 and ND2A/ND2B.
* **AQ4 — CR rejection notice.** The CR status job asks CR about every filed form every 15 minutes on PROD. DEV runs on weekdays, 08:00–16:45 HKT, because of CR TEST's hours. A rejection turns the case's CR Status red ("Rejected by CR") on the case and on the dashboard, and offers **Undo profile update**. There is no email or push notification yet. On PROD, CR has taken more than a day to list a same-day filing.
* **AQ5 — correspondence address later.** See §2.10.
* **AQ6 — e-Reg ID.** It is typed in by hand on the Person Profile's e-Registry card. CR offers no interface for G-FlowDesk to read e-Registry accounts. Sending the draft before the account exists is fine: the route is chosen at Data Verification, and the director can meanwhile sign the consent in G-FlowDesk (§2.2).
* **BQ1 — NAR1 and ND2B together.** They are two separate CR submissions, made one after the other on the same day. The Submission stage reminds the operator of the other open case. An ND2B can now proceed without the client's confirmation (§2.13).
* **BQ2 — per-company.** An ND2B is opened only for the companies ticked. The profile holds one passport and one residential address per person; a company that keeps the old details stays "pending" until it is dismissed **for that company** (§2.14).
* **BQ3 — email wording.** Please send GSHK's usual ND2A and ND2B wording; it drops into `officer_changes/emails.py` as the NAR1 letter did.
* **N1 — e-Reg vs CR.** See §2.15.

---

## 5 · Assumptions taken without asking

| # | Assumption |
|---|---|
| C-1 | Only pages 24–34 of the PDF are in scope. The document-category proposal (pp. 36–37) and the earlier wireframe feedback were not read |
| C-2 | On the e-Sign route a deferred date is entered on the **Signing** page, and CR validation moves to Signing for that case, because CR validates the dates. With every date present the existing flow stays |
| C-3 | A date the client saw cannot be changed after sending. Only a **blank** one can be filled in. Changing a seen date is still a restart |
| C-4 | With no dated change, reply-by defaults to today + 5 days (the old default was "none — operator must choose") |
| C-5 | The e-consent link is offered only to a new **natural-person director** with an email address and **no complete stored e-Registry account** at the time of sending. A body-corporate director's consent stays on paper |
| C-6 | The e-consent is presented as an electronic signature for GSHK's records and the CR-portal/paper route. Whether CR accepts it on a paper ND2A is for GSHK to confirm. e-Sign still applies CR's PIN consent |
| C-7 | The generated written resolution's wording is a standard Hong Kong board written resolution, because GSHK's sample (on the shared drive) was not available. It is **off by default**: staff preview it and tick it on |
| C-8 | Manual checks gate leaving Data Verification (validate / mark as checked), including the resignation letter and the written resolution, since GSHK says both are required before filing. A death needs no resignation letter |
| C-9 | The emailed draft (full form with PI sheets) goes to **every** recipient, including a resigning director who will see an incoming director's PI sheet. GSHK asked for the PI pages to be sent; it is one company's officers |
| C-10 | `indvHkidNo = NIL` beside a passport follows Jacqueline's CR-portal practice and the worksheet's "mandatory" flag. **Not yet run on CR TEST** (today's window had closed); the first passport-only appointee should be validated on TEST before PROD |
| C-11 | "Hong Kong company" for A10 is `incorporation_place` = HK, or a CR number when no place is recorded |
| C-12 | ND2B's anniversary default uses the open NAR1's return date, else the latest anniversary within 42 days (the NAR1 filing window). Older anniversaries would make every ND2B overdue on creation |
| C-13 | "Proceed without client confirmation" is ND2B-only and needs a reason. A client may still confirm afterwards |
| C-14 | ND2A's email keeps its current wording apart from the changes above. GSHK's own template (BQ3) has not been provided |
| C-15 | Commits stay on the local `nd2a_nd2b` branch and are not pushed. Migration 052 is not applied to DEV or PROD |
