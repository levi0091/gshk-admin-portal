/**
 * NOT a test — a visual harness for the dialogs, twin of
 * `case/__visual__.test.jsx`. Renders each modal with the real components and
 * dumps the markup so `scripts/shoot-modals.mjs` can screenshot it against the
 * real stylesheet.
 *
 * This exists because two overflow bugs shipped that no assertion would have
 * caught: a <select> takes its min-content width from its longest OPTION, so a
 * country dropdown pushed itself out through the side of a 520px dialog while
 * every test still passed. Reading JSX tells you what you wrote. A picture
 * tells you what an operator sees.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/components/__modals_visual__.test.jsx
 *   node scripts/shoot-modals.mjs
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import AddPersonModal from './AddPersonModal.jsx'
import IdentityDocumentModal from './IdentityDocumentModal.jsx'
import UploadDocumentModal from './UploadDocumentModal.jsx'
import ConfirmDialog from './ConfirmDialog.jsx'
import CloseCaseModal from './case/CloseCaseModal.jsx'
import CopyPartiesModal from './CopyPartiesModal.jsx'
import { RemoveDocumentBody } from './DocumentSections.jsx'

const get = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: vi.fn(), upload: vi.fn() },
}))
import { _resetLookups } from '../lib/lookups.js'
import { _resetDocumentSections } from '../lib/documentSections.js'

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

// The REAL shape of the offending vocabularies. `cr_country` is what blew the
// dialog open, so the harness has to carry names of the same length as CR's.
const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }, { code: 'F', label: 'Female' }],
  nationality: [
    { code: 'British', label: 'British' },
    { code: 'Chinese', label: 'Chinese (Hong Kong Special Administrative Region)' },
  ],
  cr_country: [
    { code: 'HK', label: 'Hong Kong' },
    { code: 'GB', label: 'United Kingdom of Great Britain and Northern Ireland' },
    { code: 'BQ', label: 'Bonaire, Sint Eustatius and Saba' },
  ],
  // s.653D verbatim, from services/cr_forms/control_nature.py. The second one
  // is 99 characters — the longest <option> the portal renders anywhere, and
  // therefore the widest min-content a dialog has to absorb.
  bo_owner_type: [{ code: 'ubo', label: 'Ultimate Beneficial Owner' },
                  { code: 'significant_controller', label: 'Significant Controller' }],
  bo_nature_of_control: [
    { code: 'over_25_percent',
      label: 'Holds more than 25% of the issued shares of the company' },
    { code: 'significant_influence',
      label: 'Has the right to exercise, or actually exercises, significant '
           + 'influence or control over the company' }],
}

const SECTIONS = {
  sections: [
    {
      key: 'identity', label: 'Identity Documents', is_identity: true,
      description: 'Passport, HKID and other identity documents — the numbers filed with CR',
      file_required: false,
      types: [
        { code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
        { code: 'id_passport', label: 'Passport', id_type: 'passport' },
        { code: 'id_china_id', label: 'Mainland China Identity Card', id_type: 'china_id' },
        { code: 'id_other', label: 'Other Identity Document', id_type: 'other' },
      ],
    },
    {
      key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of the residential or registered address on file',
      file_required: true,
      types: [
        { code: 'addr_utility_bill', label: 'Utility Bill', id_type: null },
        { code: 'addr_bank_statement', label: 'Bank Statement', id_type: null },
        { code: 'addr_tenancy', label: 'Tenancy Agreement', id_type: null },
        { code: 'addr_govt_letter', label: 'Government Correspondence', id_type: null },
      ],
    },
  ],
  identity_fields: {
    hkid: { fields: ['id_number'], required: ['id_number'] },
    passport: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number', 'issuing_country'],
    },
    china_id: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number'],
    },
    other: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number'],
    },
  },
}

const IDENTITY_TYPES = SECTIONS.sections[0].types

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetDocumentSections()
  get.mockImplementation(url => {
    const u = String(url)
    if (u.startsWith('/documents/sections')) return Promise.resolve(SECTIONS)
    if (u.startsWith('/documents/types')) {
      const category = new URL(u, 'http://x').searchParams.get('category')
      return Promise.resolve(
        SECTIONS.sections.find(s => s.key === category)?.types || [])
    }
    return Promise.resolve(LOOKUPS)
  })
})

const noop = () => {}

/**
 * React sets a control's value as a DOM PROPERTY, and `innerHTML` serializes
 * ATTRIBUTES — so a dump taken straight off the container shows every select
 * reading "Select…" and every input empty, whatever the component actually
 * chose. Mirroring the properties onto attributes first is what makes the
 * screenshot a picture of the real state rather than of an empty form.
 */
function freezeControlState(root) {
  for (const el of root.querySelectorAll('select')) {
    for (const opt of el.options) {
      if (opt.value === el.value) opt.setAttribute('selected', 'selected')
      else opt.removeAttribute('selected')
    }
  }
  for (const el of root.querySelectorAll('input')) {
    if (el.type === 'checkbox' || el.type === 'radio') {
      el.toggleAttribute('checked', el.checked)
    } else if (el.value) {
      el.setAttribute('value', el.value)
    }
  }
  for (const el of root.querySelectorAll('textarea')) el.textContent = el.value
}

async function dump(name, ui, settle) {
  const { container } = render(ui)
  if (settle) await settle()
  freezeControlState(container)
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), container.innerHTML, 'utf8')
}

describe.runIf(SHOOT)('modal visual harness', () => {
  it('new person', async () => {
    await dump('m1-new-person',
      <AddPersonModal onClose={noop} onCreated={noop} />,
      () => waitFor(() => screen.getByLabelText('Place of Birth')))
  })

  it('identity document — passport (the widest case)', async () => {
    // A passport shows all four fields, two of them the ones that overflowed.
    await dump('m2-identity-passport',
      <IdentityDocumentModal
        personId="p1" personName="Chan Tai Man" types={IDENTITY_TYPES}
        identityFields={SECTIONS.identity_fields} lookups={LOOKUPS}
        initialType="id_passport" onClose={noop} onSaved={noop} />,
      () => waitFor(() => screen.getByLabelText(/Issuing Country/)))
  })

  it('identity document — hkid (a number and nothing else)', async () => {
    await dump('m3-identity-hkid',
      <IdentityDocumentModal
        personId="p1" personName="Chan Tai Man" types={IDENTITY_TYPES}
        identityFields={SECTIONS.identity_fields} lookups={LOOKUPS}
        initialType="id_hkid" onClose={noop} onSaved={noop} />,
      () => waitFor(() => screen.getByLabelText(/^ID Number/)))
  })

  it('identity document — replacing one already on file', async () => {
    await dump('m4-identity-replace',
      <IdentityDocumentModal
        personId="p1" personName="Chan Tai Man" types={IDENTITY_TYPES}
        identityFields={SECTIONS.identity_fields} lookups={LOOKUPS}
        existing={[{ id: 'i1', id_type: 'passport', id_number: 'K1234567' }]}
        initialType="id_passport" onClose={noop} onSaved={noop} />,
      () => waitFor(() => screen.getByText(/REPLACES those details/)))
  })

  it('upload into a section', async () => {
    await dump('m5-upload-section',
      <UploadDocumentModal
        ownerKind="person" ownerId="p1" ownerName="Chan Tai Man"
        category="address_proof" sectionLabel="Proof of Address"
        onClose={noop} onUploaded={noop} />,
      () => waitFor(() => screen.getByRole('option', { name: 'Tenancy Agreement' })))
  })

  it('close a case — the one dialog with no undo behind it', async () => {
    // Shot FILLED IN, via `settle`. Empty it shows a disabled button and a
    // collapsed textarea, which is the state an operator spends two seconds in;
    // what wants looking at is the warning against a three-line reason and a
    // confirm field, in a `modal-sm` that has to hold both without the warning
    // text and the labels colliding.
    const user = userEvent.setup()
    await dump('m7-close-case',
      <CloseCaseModal
        caseRow={{ id: 'c1', case_no: 'NAR-2026-0041',
                   company_name: 'Harbour Tech Ltd.' }}
        onClose={noop} onClosed={noop} />,
      async () => {
        await user.type(screen.getByLabelText(/Why is this case not proceeding/),
                        'Client is dissolving the company and has instructed '
                        + 'us not to file the 2026 annual return.')
        await user.type(screen.getByLabelText(/to confirm/), 'NAR-2026-0041')
      })
  })

  it('remove a document', async () => {
    await dump('m6-remove-document',
      <ConfirmDialog title="Remove document" onCancel={noop} onConfirm={noop}>
        <RemoveDocumentBody doc={{
          id: 'd1', document_type_code: 'addr_utility_bill',
          document_types: { label: 'Utility Bill' }, file_name: 'clp-june.pdf',
        }} />
      </ConfirmDialog>)
  })

  it('copy beneficial owners — the longest option text in the app', async () => {
    // THE CASE THIS HARNESS EXISTS FOR. `bo_nature_of_control` carries a
    // 99-character option ("Has the right to exercise, or actually
    // exercises, …"), and a <select> takes its min-content width from its
    // longest OPTION — which is exactly how the country dropdown pushed itself
    // out through the side of a 520px dialog with every test still green.
    // Shot alongside a long company name and a right-hand percentage, because
    // the picker rows are the other thing here that can run out of room.
    await dump('m8-copy-beneficial-owners',
      <CopyPartiesModal
        companyId="e1"
        officers={[]}
        shareholders={[
          { id: 'sh1', person_id: 'p1', shares_held: 3000, is_current: true,
            persons: { full_name: 'Chan Tai Man' } },
          { id: 'sh2', corporate_entity_id: 'c1', shares_held: 6500,
            is_current: true,
            corporate_entity: {
              company_name: 'Sino Pacific Holdings (Hong Kong) Limited',
            } },
          { id: 'sh3', person_id: 'p3', shares_held: 500, is_current: true,
            persons: { full_name: 'Wong Siu Ming' } },
        ]}
        shareClasses={[{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                         total_issued: 10000 }]}
        existing={[{ id: 'bo1', person_id: 'p3' }]}
        onClose={noop} onSaved={noop} />,
      () => waitFor(() => screen.getByLabelText(/Nature of Control/)))
  })
})
