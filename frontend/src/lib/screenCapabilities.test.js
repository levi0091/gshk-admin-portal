import { describe, it, expect } from 'vitest'
import {
  companyProfileCaps, personProfileCaps, companyRegistryCaps,
  personsRegistryCaps, caseWorkflowCaps, crCredentialsCaps,
} from './screenCapabilities.js'

/**
 * EVERY MODULE AGAINST EVERY LEVEL, exhaustively (Levi 2026-09-04: "please make
 * sure you test thoroughly all the different read/write combinations for all
 * the different modules available").
 *
 * A render test can only ask what one screen does for one role. This asks what
 * every screen does for EVERY role, by enumerating the whole power set of the
 * portal's permissions — 2^13 = 8192 combinations — and asserting two
 * properties of each capability:
 *
 *   1. IT IS TRUE EXACTLY WHEN ITS OWN PERMISSION IS HELD. Not "when a related
 *      one is", which is how a screen ends up gating a documents action on
 *      `companies:write` and quietly granting or withholding the wrong thing.
 *   2. NO OTHER PERMISSION CHANGES IT. This is the half a hand-written test
 *      never covers: it is what catches a control that happens to work for the
 *      role you tried because that role also held something else.
 */

/** Every (module, permission) pair the portal can grant. CLAUDE.md's table. */
const ALL = [
  'companies:read', 'companies:write',
  'persons:read', 'persons:write',
  'documents:read', 'documents:write', 'documents:delete',
  'nar1:read', 'nar1:write',
  'tpsi:read', 'tpsi:write', 'tpsi:submit',
  'audit_trail:read',
]

const canFrom = held => (module, permission) => held.has(`${module}:${permission}`)

/** Every subset of ALL — 8192 of them. */
function* everyCombination() {
  for (let mask = 0; mask < (1 << ALL.length); mask++) {
    const held = new Set()
    for (let bit = 0; bit < ALL.length; bit++) {
      if (mask & (1 << bit)) held.add(ALL[bit])
    }
    yield held
  }
}

/**
 * The contract: which single permission each capability is equivalent to.
 *
 * Read this as the answer to "what do I ask an administrator for". It is
 * duplicated from `screenCapabilities.js` ON PURPOSE — a test that imported the
 * mapping it is checking would pass no matter what the mapping said.
 */
const CONTRACT = [
  ['companyProfile', companyProfileCaps, {
    editCompany: 'companies:write',
    editCorporateDetails: 'companies:write',
    toggleFlags: 'companies:write',
    editShareClasses: 'companies:write',
    editParties: 'companies:write',
    uploadDocument: 'documents:write',
    downloadDocument: 'documents:read',
    removeDocument: 'documents:delete',
    openCase: 'nar1:write',
  }],
  ['personProfile', personProfileCaps, {
    editPerson: 'persons:write',
    editIdentityDocuments: 'persons:write',
    addIdentityDocument: 'persons:write',
    uploadDocument: 'documents:write',
    downloadDocument: 'documents:read',
    removeDocument: 'documents:delete',
  }],
  ['companyRegistry', companyRegistryCaps, {
    addCompany: 'companies:write',
  }],
  ['personsRegistry', personsRegistryCaps, {
    addPerson: 'persons:write',
  }],
  ['caseWorkflow', caseWorkflowCaps, {
    editCase: 'nar1:write',
    restartVerification: 'nar1:write',
    closeCase: 'nar1:write',
    sendToClient: 'nar1:write',
    recordClientAnswer: 'nar1:write',
    uploadSignedScan: 'nar1:write',
    validate: 'tpsi:write',
    sign: 'tpsi:write',
    submit: 'tpsi:submit',
    recordOffPortalFiling: 'tpsi:submit',
  }],
  ['crCredentials', crCredentialsCaps, {
    editOwnCredential: 'tpsi:write',
  }],
]

describe.each(CONTRACT)('%s — every permission combination', (_name, caps, contract) => {
  it('grants each capability exactly when its own permission is held', () => {
    // 8192 combinations × every capability on the screen. Collected into a
    // list rather than asserted in the loop, so a failure names every
    // disagreement at once instead of stopping at the first.
    const wrong = []
    for (const held of everyCombination()) {
      const got = caps(canFrom(held))
      for (const [capability, required] of Object.entries(contract)) {
        const expected = held.has(required)
        if (got[capability] !== expected) {
          wrong.push(`${capability}: expected ${expected} for `
            + `{${[...held].sort().join(', ') || 'no permissions'}} `
            + `(needs ${required}), got ${got[capability]}`)
        }
      }
    }
    expect(wrong.slice(0, 5)).toEqual([])
  })

  it('is not influenced by any permission other than its own', () => {
    // The property a hand-written test misses. For each capability, flip every
    // OTHER permission on and off and confirm the answer never moves.
    const wrong = []
    for (const [capability, required] of Object.entries(contract)) {
      for (const holdRequired of [false, true]) {
        for (const other of ALL) {
          if (other === required) continue
          const withOther = new Set(holdRequired ? [required] : [])
          withOther.add(other)
          const without = new Set(holdRequired ? [required] : [])

          const a = caps(canFrom(withOther))[capability]
          const b = caps(canFrom(without))[capability]
          if (a !== b) {
            wrong.push(`${capability} changed when ${other} was added `
              + `(required ${required} held: ${holdRequired})`)
          }
        }
      }
    }
    expect(wrong.slice(0, 5)).toEqual([])
  })

  it('grants nothing at all to a role with no permissions', () => {
    // The freshly created account. Every screen must be inert for it.
    const got = caps(canFrom(new Set()))
    for (const capability of Object.keys(contract)) {
      expect(got[capability], capability).toBe(false)
    }
  })

  it('grants everything to a role holding every permission', () => {
    const got = caps(canFrom(new Set(ALL)))
    for (const capability of Object.keys(contract)) {
      expect(got[capability], capability).toBe(true)
    }
  })

  it('is never granted by a READ permission alone', () => {
    // Reading opens a screen; it must never be enough to change anything. This
    // is the specific regression Levi reported — a read-only role that was
    // shown every write control the screen had.
    const readsOnly = new Set(ALL.filter(p => p.endsWith(':read')))
    const got = caps(canFrom(readsOnly))
    for (const [capability, required] of Object.entries(contract)) {
      // documents:read genuinely grants downloading; nothing else is a write.
      const expected = required.endsWith(':read')
      expect(got[capability], `${capability} (needs ${required})`).toBe(expected)
    }
  })
})

describe('the module separations that actually bit', () => {
  const caps = held => ({
    company: companyProfileCaps(canFrom(new Set(held))),
    person: personProfileCaps(canFrom(new Set(held))),
    case: caseWorkflowCaps(canFrom(new Set(held))),
  })

  it('keeps documents independent of companies', () => {
    // A role may file documents against a company it cannot edit, and edit a
    // company whose documents it may not touch. Both directions.
    const docsOnly = caps(['companies:read', 'documents:write', 'documents:read'])
    expect(docsOnly.company.uploadDocument).toBe(true)
    expect(docsOnly.company.downloadDocument).toBe(true)
    expect(docsOnly.company.editCompany).toBe(false)

    const companyOnly = caps(['companies:read', 'companies:write'])
    expect(companyOnly.company.editCompany).toBe(true)
    expect(companyOnly.company.uploadDocument).toBe(false)
    expect(companyOnly.company.downloadDocument).toBe(false)
    expect(companyOnly.company.removeDocument).toBe(false)
  })

  it('keeps documents:delete apart from documents:write', () => {
    // Uploading a new version is not the same act as destroying what is filed.
    const writeNotDelete = caps(['documents:read', 'documents:write'])
    expect(writeNotDelete.company.uploadDocument).toBe(true)
    expect(writeNotDelete.company.removeDocument).toBe(false)
  })

  it("treats a person's IDENTITY documents as persons, not documents", () => {
    // An identity record is part of the person even when it carries a scan:
    // POST /persons/{id}/identity-documents is gated on persons:write.
    const personsOnly = caps(['persons:read', 'persons:write'])
    expect(personsOnly.person.addIdentityDocument).toBe(true)
    expect(personsOnly.person.editIdentityDocuments).toBe(true)
    // ...and the scan itself is still a document, which this role cannot read.
    expect(personsOnly.person.downloadDocument).toBe(false)
    expect(personsOnly.person.uploadDocument).toBe(false)
  })

  it('keeps opening a case out of companies:write', () => {
    // Editing a company profile does not entitle you to drive a statutory
    // filing.
    const companyEditor = caps(['companies:read', 'companies:write'])
    expect(companyEditor.company.editCompany).toBe(true)
    expect(companyEditor.company.openCase).toBe(false)
  })

  it('keeps SPENDING MONEY behind tpsi:submit and nothing else', () => {
    // The one irreversible, chargeable act in the portal. A role that can
    // prepare, validate and sign still cannot file.
    const preparer = caps(['nar1:read', 'nar1:write', 'tpsi:read', 'tpsi:write'])
    expect(preparer.case.validate).toBe(true)
    expect(preparer.case.sign).toBe(true)
    expect(preparer.case.submit).toBe(false)
    expect(preparer.case.recordOffPortalFiling).toBe(false)
  })

  it('gates the OFF-PORTAL filing exactly as the real one', () => {
    // Recording a paper filing closes the case as filed, so it costs the same
    // permission as a CR submit — not nar1:write.
    const caseWorker = caps(['nar1:read', 'nar1:write'])
    expect(caseWorker.case.uploadSignedScan).toBe(true)
    expect(caseWorker.case.recordOffPortalFiling).toBe(false)

    const filer = caps(['nar1:read', 'tpsi:submit'])
    expect(filer.case.recordOffPortalFiling).toBe(true)
    expect(filer.case.submit).toBe(true)
  })

  it('validates on tpsi:WRITE, not tpsi:read', () => {
    // The screen used to promise `tpsi:read`. Validating rebuilds the draft
    // first (`filings/prepare`, tpsi:write), so a read-only role following that
    // tag would have asked for a permission that could not complete the action.
    const reader = caps(['nar1:read', 'tpsi:read'])
    expect(reader.case.validate).toBe(false)

    const writer = caps(['nar1:read', 'tpsi:write'])
    expect(writer.case.validate).toBe(true)
  })
})

describe('the shared CR presenter credential', () => {
  const can = held => canFrom(new Set(held))

  it('is super_admin only — tpsi:write is NOT enough', () => {
    // One CR filing identity is shared by the whole portal (migration 020).
    // Holding tpsi:write must not let a user repoint every future filing at
    // another CR account.
    const withWrite = crCredentialsCaps(can(['tpsi:write']), false)
    expect(withWrite.editOwnCredential).toBe(true)
    expect(withWrite.editSharedCredential).toBe(false)
  })

  it('is granted to a super admin', () => {
    expect(crCredentialsCaps(can(['tpsi:write']), true).editSharedCredential)
      .toBe(true)
  })

  it('is not granted by every permission short of super_admin', () => {
    expect(crCredentialsCaps(can(ALL), false).editSharedCredential).toBe(false)
  })
})
