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
    // POST /companies/{id}/documents
    uploadDocument: can('documents', 'write'),
    // GET /documents/{id}/download
    downloadDocument: can('documents', 'read'),
    // DELETE /documents/{id} — a THIRD level on the documents module.
    removeDocument: can('documents', 'delete'),
    // POST /cases. Deliberately not `companies:write`: editing a profile does
    // not entitle you to drive a statutory filing.
    openCase: can('nar1', 'write'),
  }
}

/**
 * Person profile (`GET /persons/{id}`, opened by `persons:read`).
 *
 * THE IDENTITY DOCUMENTS ARE `persons`, NOT `documents`. A passport record is
 * part of the person — `POST /persons/{id}/identity-documents` is gated on
 * `persons:write` — even though it can carry a scan. Only the SCAN is a
 * document, so only downloading it asks the documents module.
 */
export function personProfileCaps(can) {
  return {
    editPerson: can('persons', 'write'),
    editIdentityDocuments: can('persons', 'write'),
    addIdentityDocument: can('persons', 'write'),
    uploadDocument: can('documents', 'write'),
    downloadDocument: can('documents', 'read'),
    removeDocument: can('documents', 'delete'),
  }
}

/** Both registries: the list is the read, the Add button is the write. */
export function companyRegistryCaps(can) {
  return { addCompany: can('companies', 'write') }
}

export function personsRegistryCaps(can) {
  return { addPerson: can('persons', 'write') }
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
