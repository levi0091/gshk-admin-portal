# Queued work

Raised by Levi, not yet started. Newest first. Delete an item when it ships.

---

## Q3 · Workflow screens have drifted from wireframe_v11 — 2026-08-30

Levi: *"the workflow pages are quite different from wireframe_v11. please look
and compare thoroughly... especially the signing page. Please go through each
page of the workflow for the wireframe and compare with dev environment. unless
there is a good reason the design interface should be similar."*

Compare **every** workflow stage against `wireframe_v11`, screen by screen, and
bring the built UI back to it. Where the build deliberately differs, the reason
has to be stated — drift without a reason is the thing being corrected.

The **Signing** stage is the worst of them, and Levi supplied a screenshot of
what v11 specifies. What v11 has that the built screen does not:

- **"Choose the signatory" — a radio list of the actual people**, each showing
  their name (English + Chinese), their CR e-Service ID as a chip, and their
  role ("Director of the company", "Authorised representative of the company
  secretary · Get Started HK Limited"). A person with **no e-Service ID on file
  is listed but disabled**, with the reason and the remedy spelled out: *"No CR
  e-Service ID on file. Add one on this person's Persons Registry profile
  before they can sign."*
- The built screen instead offers two bare text inputs — "Signatory e-Service
  user ID" and "e-Service signing password" — with no list of who may sign.
- **Signing-method cards** (e-Sign vs Manual) rendered as two selectable cards
  with their consequences written out, not a plain toggle.
- **A deposit-balance strip** above the signature block: balance, the fee it
  covers, TPSI password expiry warning, and `Checked just now ·
  enquireDepositAccount`.
- **An explanatory strip**: *"A NAR1 carries one signature by a single
  authorised individual... Signing calls `verifyPinSigningNar1` and is free;
  nothing is charged until Submission."*
- Header: workflow badge + **CR FORM** badge side by side, `Module:
  case_management` chip, **Restart verification** and **Save** buttons.

Note Q1 below overlaps this: the signatory list becomes moot if only the
logged-in user may sign, so **do Q1 first and re-read v11's signing screen in
that light.**

---

## Q2 · Resend API key has been replaced — 2026-08-30

Levi: *"I have updated the resend api key you can now give it a try."*

The old value was the literal placeholder `your-resend-api-key`. Verify the new
one against `GET https://api.resend.com/domains`, confirm `getstarted.hk` is
verified for SPF/DKIM, then send a real client-verification mail on DEV — it
will land on the four `TEST_RECIPIENTS`, never a client.

If it works: **retire `EMAIL_TRANSPORT=console`.** Its only remaining reason to
exist is that there was no key. Protecting clients is no longer its job —
`email_service.TEST_RECIPIENTS` does that unconditionally. Removing it means
deleting the branch, its guards, its tests, and the notes in `CLAUDE.md` and
`.env.example`.

Also still outstanding from before: Railway DEV needs `EMAIL_TRANSPORT=console`
set, or a working `RESEND_API_KEY` — `POST /verification/send` answers 503
there today.

---

## Q1 · A NAR1 may only be signed with the logged-in user's own e-Reg — 2026-08-30

Levi: *"for NAR1 we should only sign using the e-reg of the logged in user."*

Today `POST /tpsi/filings/{id}/sign` accepts `signatory_user_id` +
`eservice_password` in the request body and signs as whoever is named
(`routers/tpsi.py` ~786). That has to go: the signature must come from the
signed-in user's own stored e-Service credential and nothing else.

Consequences to work through:

- Drop `signatory_user_id` / `eservice_password` from the request body, or
  refuse them outright rather than ignoring them silently.
- A user with no stored e-Service credential can no longer sign at all — the
  screen has to say so and point at CR Credentials.
- The **client-director signing path disappears.** The current UI copy promises
  it ("A client director's password is never stored — they enter it at the
  moment of signing"). That promise has to come out of the CR Credentials
  screen and the Signing stage.
- `signatory_capacity` (migration 026) stays, but the resolved signatory should
  now be derived from the logged-in user rather than from the company's officer
  list — check `nar1_mapper._derive_signatory` still tells the truth.
- Recheck against CR: it refuses a signature from anyone not associated with the
  company by officer appointment (`ERR_MSG_SIGNATORY_NOT_AUTH`), so restricting
  to the logged-in user only works where that user IS an appointed officer.
  Confirm that holds for GSHK's staff accounts before shipping.
- Interacts with Q3 — v11's "Choose the signatory" radio list may become a
  single fixed row.
