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

/**
 * Every (module, permission) pair the portal can grant. CLAUDE.md's table.
 *
 * `documents:read/write/delete` ARE NOT HERE ANY MORE (Levi 2026-09-07,
 * migration 040). The module is gone: a document is filed against a company, a
 * person or a case and takes that record's grant. Leaving the three in this
 * list would keep the power set honest about a permission nobody can be given,
 * and — worse — the "no other permission moves this" property below would still
 * pass while asserting nothing about the modules that now decide.
 */
const ALL = [
  'companies:read', 'companies:write',
  'persons:read', 'persons:write',
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
    // A company's papers follow the company (migration 040). `removeDocument`
    // is a WRITE, not a delete level — `companies` has none, and removing a
    // document is a change to what the record holds.
    uploadDocument: 'companies:write',
    downloadDocument: 'companies:read',
    removeDocument: 'companies:write',
    openCase: 'nar1:write',
  }],
  ['personProfile', personProfileCaps, {
    editPerson: 'persons:write',
    editIdentityDocuments: 'persons:write',
    addIdentityDocument: 'persons:write',
    // Now the same grant the identity documents beside them always used.
    uploadDocument: 'persons:write',
    downloadDocument: 'persons:read',
    removeDocument: 'persons:write',
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

  // REVERSES "keeps documents independent of companies" (Levi 2026-09-07).
  //
  // That test asserted the old three-module split — "a role may file documents
  // against a company it cannot edit, and edit a company whose documents it may
  // not touch, both directions" — and both directions turned out to be bugs
  // wearing a principle's clothes. Migration 040 drops the module; a document
  // now follows the record it is filed against.

  it("gives a company's papers to whoever holds the company", () => {
    // The complaint: a role granted Companies (edit) could not upload the
    // certificate of incorporation for a company it was trusted to edit the CR
    // number of, and had to be given a second grant nobody knew to ask for.
    const companyEditor = caps(['companies:read', 'companies:write'])
    expect(companyEditor.company.editCompany).toBe(true)
    expect(companyEditor.company.uploadDocument).toBe(true)
    expect(companyEditor.company.downloadDocument).toBe(true)
    expect(companyEditor.company.removeDocument).toBe(true)
  })

  it('lets a company READER download but never upload or remove', () => {
    // Reading opens the record and the papers on it. Changing what the record
    // holds is a write, and that includes removing a document.
    const reader = caps(['companies:read'])
    expect(reader.company.downloadDocument).toBe(true)
    expect(reader.company.uploadDocument).toBe(false)
    expect(reader.company.removeDocument).toBe(false)
    expect(reader.company.editCompany).toBe(false)
  })

  it("gives a person's papers to whoever holds the person", () => {
    // The identity documents were ALWAYS `persons` — an identity record is
    // part of the person even when it carries a scan. What changed is that the
    // ordinary documents beside them now agree, which is what an operator
    // already assumed was true.
    const personEditor = caps(['persons:read', 'persons:write'])
    expect(personEditor.person.addIdentityDocument).toBe(true)
    expect(personEditor.person.editIdentityDocuments).toBe(true)
    expect(personEditor.person.uploadDocument).toBe(true)
    expect(personEditor.person.downloadDocument).toBe(true)
    expect(personEditor.person.removeDocument).toBe(true)
  })

  it("does not let a company grant reach a PERSON's documents", () => {
    // The module is read off the record, not off the caller's best grant. A
    // role that may edit companies has no business removing a director's
    // identity scan.
    const companyEditor = caps(['companies:read', 'companies:write'])
    expect(companyEditor.person.downloadDocument).toBe(false)
    expect(companyEditor.person.uploadDocument).toBe(false)
    expect(companyEditor.person.removeDocument).toBe(false)
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
