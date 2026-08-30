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

Q1 has since shipped, which **settles the first two bullets**: there is no
signatory list any more, because who signs is the session's and not a choice.
v11's "Choose the signatory" radio list must be read in that light — what
survives of it is a single row naming the logged-in user's e-Service account.
The rest of the list stands.

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
