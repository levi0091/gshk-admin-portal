# ND2A / ND2B — Levi's revisions of 4–5 October 2026

Revises `2026-10-02-nd2-jacqueline-feedback-design.md` (§2.2, §2.3, §2.4, §2.14)
and adds per-company particulars. Levi's instructions were given in chat and are
quoted below; he asked for everything to be built and pushed without questions,
so every open point is decided here and listed in §9.

---

## 1 · Consent to act — no inked page, no link (ND2A point 2)

> "can you check if we sign with e-reg account of new director will it still be
> necessary to get the inked signature on a pdf? If it is not necessary … then
> there is no need for the email to include sign consent to act. … when
> additional director has no e-reg account or does not want us to sign on behalf
> then it will just go the manual route with CR portal."

**Finding.** CR's TPSI API Interface v1.0.14 §7.1.2: *"The consent signature is
used to sign each director's consent form."* The PinSign over the director's
`indDir`/`corpDir` bean, made with the director's own e-Registry account, IS the
consent CR receives. No inked consent page is needed on the e-Sign route.

**Change.** The in-portal consent ("Sign consent to act" button, its public
page, its tokens, the stamped PDF, `OFFICER_ECONSENT_*`) is removed — from code
and from migration 052, which no database has run (DEV has neither 050 nor 052,
checked 2026-10-05). The email carries no consent paragraph. A new director
whose e-Registry account is not stored makes e-Sign unavailable, and the reason
says to file on the manual route (CR portal, then the manual workflow).

## 2 · Written resolution — GSHK's sample, exactly (ND2A point 3)

> "build exactly to this written resolution sample … in font size, wordings and
> everything. For change of director or change of company secretary, you will
> show 2 pdfs as preview .. a tab button on top of the pdf viewer … When they
> click send to client button then both are sent … the manual checks should not
> include the signed written resolution afterall.. and no consent to act.."

Source: `Sample Written Resolution - Change of Director.pdf` (Word, Letter).
Measured with PyMuPDF; the renderer reproduces:

| | |
|---|---|
| page | US Letter 612 × 792 pt, left text edge x = 72 |
| face | Times New Roman 12 pt (Tinos, metric-identical); bold for header and headings. Chinese in Noto Sans TC 12 pt (the sample's DengXian is a Microsoft sans and cannot be shipped) |
| header | two black rules 1.44 pt thick, x 70.58–541.53, at y 86.42 and 179.54; between them four bold centred lines, baselines 112.9 / 128.8 / 144.6 / 160.5: `WRITTEN RESOLUTIONS OF` · company name · `(Business Registration No. N)` · `(the “Company”)` |
| headings | bold, underlined (1.2 pt rule just below the baseline) |
| body | regular, left at x 72, wrapped at x 540 |
| line pitch | 13.8 pt; a line carrying Chinese, and the header, 15.9 pt (Word's line height for DengXian) |
| gaps | as the sample: 1 blank line after a heading, 2 after a resolution, 5 before `Dated:`, 4 before the signature line |
| signature | at x 77.4: 36 underscores · `Name: <name>` · `Director` |

Wording is the sample's. One edit, a ruling (§9 R-1): the sample's resignation
sentence reads *"shall resign as director effective from the company effective
from the date hereof"*, an evident drafting slip; the renderer prints *"shall
resign as director of the company effective from the date hereof"*. It is one
constant.

Cases the sample does not show (§9 R-2): a company secretary uses the same
sentences with "company secretary"; a death reads *"IT IS NOTED that X ceased to
be a director of the company by reason of death."* under "Cessation of
Director"; two or more of one kind get one heading in the plural; the closing
sentence starts "This change" / "Both changes" / "All changes"; `Dated:` prints
the effective date when every change shares one, else a blank line; one
signature block per director in office after the changes.

**Client Verification** for an ND2A shows a tab bar above the PDF viewer —
**ND2A** | **Written Resolution**. **Send to client** attaches both, always:
`attach_resolution` and its toggle are removed. The case's own uploads stay
("Other document", ticked to go with the email). ND2B: the form only, no tabs.

**Manual checks**: KYC per new officer and a resignation letter per leaver.
The written-resolution and consent-to-act checks are removed.

## 3 · Consent signature status (ND2A point 5)

> "you need to enter the director's e-reg account's username and password into
> his natural person's profile page. Whatever username and password you entered
> there will be used to pin-sign. … So when you click on Apply consent signature
> it will just tell you if CR portal recognised their username and password as
> pin-signed. If no issues … it will show as 'Signed' status. If there is any
> issue then the status will be 'Error' and it will show the error that CR
> portal return to us."

Each consent row on Signing carries `status`: `signed` (consent signed), `error`
with CR's own message (the last signing call failed), or `not_signed`. The
button reads **Apply consent signature** when the form has consents. CR takes
every signature in one `verifyPinSigning` call, so a refusal is shown on every
consent row, unless CR's text names one signer's bean id or e-Registry user ID
(then on that row only). The Person Profile's e-Registry card states Levi's
rule: the username and password stored there are what G-FlowDesk PIN-signs the
director's consent with.

## 4 · NAR1 after an ND2A (ND2A question 3)

> "if user submitted nd2a and the company profile director changed... then for
> nar1 submission page, when user click submit and the data is different it
> should stop the submission and warn right?"

Yes, already: `filings._refuse_if_drifted` rebuilds the NAR1 from the company
record before any CR call and refuses with `DriftDetected` (409, the changed
fields listed) when it differs from what was validated. A regression test pins
the ND2A case.

## 5 · ND2B — dismissed once filed with one company

> "We will dismiss the change not yet filed warning after it has been filed with
> at least one company"

When an ND2B is filed for one company, the same change (same CR item, same new
value) stops being reported for the party's other companies: their baselines
move forward for those items (`source = 'dismissed'`), audited as
`OFFICER_PARTICULARS_DISMISSED` with `reason: filed_with_another_company`. A
company with its own open ND2B is left alone. Other pending items are untouched.

## 6 · Per-company particulars (ND2B question 2)

> "build a link between person's identification and person's residential and
> correspondence address with different companies. maybe the residential address
> field can be a list of addresses … in each residential address in the list it
> shows which companies is using those addresses. same design applied to
> correspondence address.. same for identification … we are already storing
> multiple identifications but one is primary... but different identifications
> can be linked to different companies too"

**Model (migration 053).**

* `person_addresses (person_id, address_id, kind residential|correspondence)` —
  the person's address book. Backfilled from `persons.residential_address_id`
  and from every officer row's `correspondence_address_id`.
* `entity_officers.residential_address_id` and
  `entity_officers.identity_document_id` — what ONE appointment files. NULL
  follows the person: the default residential address
  (`persons.residential_address_id`), the primary document of each type.
  `correspondence_address_id` already exists (NULL = same as residential).
* A linked identity document replaces the person's primary document **of its
  type** for that company.

**Who reads it.** `services/officer_changes/links.py` resolves one
appointment's effective particulars. NAR1's mapper, the drift check (same
mapper), an ND2A cessation, and the ND2B baseline/diff all go through it, so a
company linked to the US passport files the US passport everywhere. A party
nobody linked behaves exactly as before.

**API** (`persons:write` / `persons:read`, `live_person`; writes audited as
`CASE_FIELD_UPDATED` on the person with the field and company in metadata; the
ND2B baseline for each company the write moves is captured first):

| route | |
|---|---|
| `GET /persons/{id}/particulars-by-company` | appointments, residential and correspondence address books, identity documents, each with `used_by` |
| `POST /persons/{id}/addresses` | add a residential or correspondence address; optional companies; `make_default` (residential) |
| `PUT /persons/{id}/addresses/{address_id}` | correct the address — copy-on-write, every company using it moves with it |
| `PUT /persons/{id}/addresses/{address_id}/companies` | which companies use it |
| `POST /persons/{id}/addresses/{address_id}/default` | residential default |
| `DELETE /persons/{id}/addresses/{address_id}` | refused while default or in use |
| `PUT /persons/{id}/identity-documents/{doc_id}/companies` | which companies file this document |

**Screen.** The Person Profile's Residential Address block and the
Correspondence Address card are replaced by three cards — Identification,
Residential addresses, Correspondence addresses — each listing its entries with
the companies using each, a **New** button, and a **Companies…** picker.
Shareholders' Schedule 1 addresses are not linked (§9 R-6).

## 7 · Data, permissions, audit

No new module, no new permission. No new audit code: link changes are
`CASE_FIELD_UPDATED`, the automatic dismissal is `OFFICER_PARTICULARS_DISMISSED`.
Migration 052 loses `officer_change_consents`, `attach_resolution`,
`source`/`uploaded_by_name` and the two `OFFICER_ECONSENT_*` codes. Migration 053
is new and reversible; its downgrade refuses while any link is set.

## 8 · Tests

Resolution geometry against the sample's measurements; e-consent removal
(routes 404, email has no link); manual checks; send attaches both PDFs;
consent status signed/error/not signed; drift after ND2A; auto-dismissal
(same item and value only, open ND2B skipped); links resolver; NAR1 mapper and
ND2B diff honour links; every new route's happy path, 401/403 and an edge case;
the three profile cards.

## 9 · Rulings taken without asking

| | |
|---|---|
| R-1 | The sample's resignation sentence is corrected to "…as director of the company effective from the date hereof." One constant to revert |
| R-2 | Secretary, death, plural and closing-sentence variants as §2 |
| R-3 | Chinese prints in Noto Sans TC Regular (instanced from Google Fonts' variable Noto Sans TC, OFL) — DengXian cannot be shipped |
| R-4 | A CR signing refusal shows on every consent row unless CR names the signer |
| R-5 | The automatic dismissal applies only to the same item with the same new value, and skips a company with its own open ND2B |
| R-6 | Shareholders' Schedule 1 addresses are not per-company — the request was about officers |
| R-7 | Correcting an address is copy-on-write for this person only; another person sharing the row is untouched |
| R-8 | The old `GET/PUT …/correspondence-address(es)` routes stay for compatibility; the screen no longer uses them |
| R-9 | 052 is edited in place, not followed by a dropping migration — no database has run it |
