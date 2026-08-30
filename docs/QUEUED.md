# Queued work

Raised by Levi, not yet started. Newest first. Delete an item when it ships.

Nothing queued. Q1 (sign with the logged-in user's e-Reg), Q2 (the real Resend
key, and retiring EMAIL_TRANSPORT=console) and Q3 (bring the five workflow
stages back to wireframe_v11) all shipped on 2026-08-30.

Still open, but not queued work — they need a CR filing window, Mon-Fri
10:00-16:00 HKT:

- **Q1 needs one live signature to be proven.** The change assumes GSHK staff
  e-Service accounts are authorised because GSHK Ltd is the appointed company
  secretary. If CR requires the signing account to be personally appointed
  (`ERR_MSG_SIGNATORY_NOT_AUTH`), Q1 makes NAR1 unsignable rather than safer.
- **The regression's phase 2** (validate real companies at scale) has never had
  its live run; phase 3 additionally needs `scripts/prep_case_for_signing.py`,
  which `frontend/e2e/nar1-sign-submit.spec.js` references and which is not in
  the repo.
- **Railway DEV still needs `RESEND_API_KEY` set.** `POST /verification/send`
  answers 503 there. `EMAIL_TRANSPORT=console` is no longer an escape hatch —
  setting it now fails at startup by design.
