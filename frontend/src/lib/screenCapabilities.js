/**
 * WHICH CONTROL NEEDS WHICH PERMISSION — one answer per screen, in one place.
 *
 * This used to be a scatter of `hasPermission('companies', 'write')` calls
 * inline in JSX, which had two costs. It could drift from the API (the case
 * screen told operators to ask for `tpsi:read` to validate, when validating
 * rebuilds the draft and needs `tpsi:write`; and it named a module,
 * `case_management`, that does not exist and could not be granted). And it
 * could not be tested across combinations — you can assert what one screen does
 * for one role, but not that every screen agrees with the API for every role.
 *
 * Each function takes `can(module, permission)` and returns a flat set of
 * booleans, one per control the screen offers. They are pure, so
 * `__permission_matrix__.test.jsx` walks every module/level combination through
 * them; the screens read the same functions, so what the tests describe is what
 * renders.
 *
 * THE MODULE AND LEVEL ON EVERY LINE IS THE API'S, NOT A GUESS. Each is the
 * guard on the route the control calls — see the table in CLAUDE.md and the
 * `require_permission(...)` on each handler. When they disagree, the API wins
 * and this file is the bug.
 */

/**
 * Company profile (`GET /companies/{id}`, opened by `companies:read`).
 *
 * THREE MODULES MEET HERE and are asked separately, because a role can hold any
 * of them without the others: the company record itself, the documents filed
 * against it, and the NAR1 case opened from it.
 */
export function companyProfileCaps(can) {
  return {
    // PATCH /companies/{id}, /flags, /company-phone, /registered-address,
    // /share-classes, POST+PATCH+DELETE /{relation} — all `companies:write`.
    editCompany: can('companies', 'write'),
    editCorporateDetails: can('companies', 'write'),
    toggleFlags: can('companies', 'write'),
    editShareClasses: can('companies', 'write'),
    editParties: can('companies', 'write'),
    // POST /companies/{id}/documents, GET /documents/{id}/download,
    // DELETE /documents/{id} — ALL ON `companies` (Levi 2026-09-07). There is
    // no documents module any more: the papers filed against a company are
    // part of that record, so the right to change the record is the right to
    // add and remove them. Removing a document IS changing what the record
    // holds, so it is a write -- not `companies:delete`, which is the right to
    // delete the company itself.
    uploadDocument: can('companies', 'write'),
    downloadDocument: can('companies', 'read'),
    removeDocument: can('companies', 'write'),
    // POST /cases. Deliberately not `companies:write`: editing a profile does
    // not entitle you to drive a statutory filing.
    openCase: can('nar1', 'write'),
    // POST /companies/{id}/delete and /restore (migration 049). Its own level:
    // editing a company is not the right to make it disappear.
    deleteCompany: can('companies', 'delete'),
    restoreCompany: can('companies', 'delete'),
    // POST /officer-changes (ND2A / ND2B, migration 050) — the Report a change
    // menu and each officer's Cease / Change particulars. Its own module for the
    // same reason `openCase` is not `companies:write`: it drives a filing.
    startOfficerChange: can('officer_changes', 'write'),
    // GET /officer-changes/pending — the "Change pending" chips.
    viewOfficerChanges: can('officer_changes', 'read'),
    // GET / POST /companies/{id}/particulars-changes[/dismiss] — the alert on a
    // body corporate officer's own profile. Reading it is reading the company;
    // dismissing it moves what the company record holds as CR's view.
    viewParticularsChanges: can('companies', 'read'),
    dismissParticularsChange: can('companies', 'write'),
  }
}

/**
 * A DELETED record's profile: everything withdrawn but reading its papers and
 * restoring it. The API refuses every write on a deleted record with a 404, so
 * any other control would only ever produce that.
 */
export function asDeleted(caps) {
  const keep = new Set(['downloadDocument', 'restoreCompany', 'restorePerson'])
  return Object.fromEntries(
    Object.entries(caps).map(([name, allowed]) => [name, keep.has(name) && allowed]))
}

/**
 * Person profile (`GET /persons/{id}`, opened by `persons:read`).
 *
 * EVERY LINE IS `persons` NOW (Levi 2026-09-07). The identity documents always
 * were — a passport record is part of the person, and
 * `POST /persons/{id}/identity-documents` is gated on `persons:write` — while
 * the ordinary documents beside them asked a separate `documents` module. So a
 * role could add a director's passport record and be refused the proof of
 * address filed underneath it, which is not a distinction anybody wanted to
 * make. The module is gone; a person's papers follow the person.
 */
export function personProfileCaps(can) {
  return {
    editPerson: can('persons', 'write'),
    editIdentityDocuments: can('persons', 'write'),
    addIdentityDocument: can('persons', 'write'),
    uploadDocument: can('persons', 'write'),
    downloadDocument: can('persons', 'read'),
    // Removing a document IS changing what the record holds, so a write.
    removeDocument: can('persons', 'write'),
    // POST /persons/{id}/delete and /restore (migration 049).
    deletePerson: can('persons', 'delete'),
    restorePerson: can('persons', 'delete'),
    // GET / PUT / DELETE /persons/{id}/eservice-credential (migration 050). The
    // person's e-Registry account is part of the person, like their passport.
    viewEServiceCredential: can('persons', 'read'),
    editEServiceCredential: can('persons', 'write'),
    // GET / POST /persons/{id}/particulars-changes[/dismiss].
    viewParticularsChanges: can('persons', 'read'),
    dismissParticularsChange: can('persons', 'write'),
    // POST /officer-changes — Start ND2B from the alert; opening one is a read.
    startOfficerChange: can('officer_changes', 'write'),
    viewOfficerChanges: can('officer_changes', 'read'),
  }
}

/**
 * Both registries: the list is the read, the Add button is the write, and the
 * Deleted tab -- GET /companies/deleted, /persons/deleted -- is the delete
 * level, because it exists to restore from.
 */
export function companyRegistryCaps(can) {
  return {
    addCompany: can('companies', 'write'),
    viewDeleted: can('companies', 'delete'),
  }
}

export function personsRegistryCaps(can) {
  return {
    addPerson: can('persons', 'write'),
    viewDeleted: can('persons', 'delete'),
  }
}

/**
 * The NAR1 case workflow (`GET /cases/{id}`, opened by `nar1:read`).
 *
 * FOUR LEVELS ACROSS TWO MODULES, and the separation is the point — the money
 * is behind its own permission:
 *
 *   nar1:write   the case itself — ticks, capacity, method, sending to the
 *                client, recording their answer, the wet-signed upload
 *   tpsi:write   talking to CR — building the draft, validating it, PIN-signing
 *   tpsi:submit  spending money — the real submit, and recording an off-portal
 *                filing, which closes the case exactly as a real one does
 */
export function caseWorkflowCaps(can) {
  return {
    // PATCH /cases/{id}
    editCase: can('nar1', 'write'),
    restartVerification: can('nar1', 'write'),
    // POST /cases/{id}/close — IRREVERSIBLE, and `nar1:write` deliberately.
    // The two writes on `tpsi:submit` are there because they spend money or
    // commit a filing; closing does neither. Its own entry rather than reusing
    // `editCase`: this file is what the screens read to decide what to render,
    // and "the button that ends a case for good" is not the same control as
    // "the button that ticks AML", however the two happen to be gated today.
    closeCase: can('nar1', 'write'),
    // POST /cases/{id}/verification/send and /response
    sendToClient: can('nar1', 'write'),
    recordClientAnswer: can('nar1', 'write'),
    // POST /cases/{id}/manual-sign
    uploadSignedScan: can('nar1', 'write'),
    // POST /tpsi/filings/prepare (write) then /{id}/validate (read). WRITE is
    // the binding one: validation rebuilds the draft first, so a role with read
    // alone cannot complete the action.
    validate: can('tpsi', 'write'),
    // POST /tpsi/filings/{id}/sign
    sign: can('tpsi', 'write'),
    // POST /tpsi/filings/{id}/submit — chargeable and irreversible.
    submit: can('tpsi', 'submit'),
    // POST /cases/{id}/manual-submit and /manual-receipt. Same permission as a
    // real submit, because it closes the case as filed just the same.
    recordOffPortalFiling: can('tpsi', 'submit'),
  }
}

/**
 * The ND2A / ND2B case (`GET /officer-changes/{id}`, opened by
 * `officer_changes:read`). The same split as the NAR1 case: the case on its own
 * module, talking to CR on `tpsi:write`, and committing the filing on
 * `tpsi:submit` — on both routes, because recording a CR-portal filing updates
 * the profiles exactly as the e-Sign submit does.
 */
export function officerChangeCaps(can) {
  return {
    // PATCH /officer-changes/{id}, entries, KYC, documents, send, response,
    // close, mark-checked, signed-form.
    editCase: can('officer_changes', 'write'),
    // POST /officer-changes/{id}/validate and /sign.
    validate: can('tpsi', 'write'),
    sign: can('tpsi', 'write'),
    // POST /officer-changes/{id}/submit, /receipt, /record-filing, /undo.
    submit: can('tpsi', 'submit'),
    recordOffPortalFiling: can('tpsi', 'submit'),
    undoProfileUpdate: can('tpsi', 'submit'),
    // POST /tpsi/cases/{id}/refresh-status — the poller NAR1 uses.
    checkCrStatus: can('tpsi', 'read'),
  }
}

/**
 * CR credentials. The user's OWN signing identity is `tpsi:write`; the SHARED
 * presenter credential is `super_admin` itself, not a tpsi level — one CR
 * filing identity is shared by the whole portal, and holding `tpsi:write` must
 * not let a user repoint every future filing at another CR account.
 */
export function crCredentialsCaps(can, isSuperAdmin = false) {
  return {
    editOwnCredential: can('tpsi', 'write'),
    editSharedCredential: Boolean(isSuperAdmin),
  }
}
