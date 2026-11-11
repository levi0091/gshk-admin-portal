// ND2A / ND2B action rows and buttons line up (2026-11-12 alignment pass).
//
// Three defects found on DEV, all of the same family:
//   1. `.oc-send-row > .btn { margin-top: 21.5px }` dropped EVERY stage button
//      21.5px — right only for the Reply-by date box it was written for. On the
//      other rows the button hung below and to the side of its badge or hint.
//   2. `.btn` had a fixed height and no `white-space`, so "Add officer" on the
//      ND2B card wrapped to two lines inside a 36px box.
//   3. The Confirmation stage's Undo was a bare row under the last card.
// jsdom does not lay anything out, so the CSS half is asserted as a contract
// on the stylesheet, and the markup half by where each control renders.
import fs from 'node:fs'
import path from 'node:path'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import StageDataVerification from './StageDataVerification.jsx'
import StageConfirmation from './StageConfirmation.jsx'

vi.mock('../../lib/api.js', () => ({
  api: {
    get: vi.fn(() => Promise.resolve({})), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
    upload: vi.fn(), blob: vi.fn(() => Promise.resolve(new Blob())), put: vi.fn(),
  },
}))

const read = p => fs.readFileSync(path.resolve(process.cwd(), p), 'utf8')
const OC_CSS = read('src/components/officerChange/officerChange.css')
const INDEX_CSS = read('src/index.css')
// The body of the first rule whose selector is exactly `sel`.
const rule = (css, sel) => {
  const esc = sel.replace(/[.*+?^${}()|[\]\\>]/g, '\\$&')
  const m = css.match(new RegExp(`(^|\\n)\\s*${esc}\\s*\\{([^}]*)\\}`))
  return m ? m[2] : null
}

const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }
const BASE = {
  id: 'k1', case_no: 'ND2A-2026-0001', form_code: 'Nd2a', case_type: 'ND2A', editable: true,
  officers: [
    { officer_id: 'o1', role: 'director', party_type: 'individual', name: 'CHAN Tai Man', pending: false },
  ],
  entries: [], route: { esign_available: true, reasons: [], consents: [] },
  signatory: { name: 'GSHK Ltd', capacities: ['Director of the Company Secretary (Body Corporate)'] },
  client_approved: true,
}
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('stylesheet contract', () => {
  it('no longer drops every button in an action row', () => {
    expect(rule(OC_CSS, '.oc-send-row > .btn')).toBeNull()
  })

  it('keeps the drop only beside a labelled field', () => {
    expect(rule(OC_CSS, '.oc-send-row-field > .btn')).toMatch(/margin-top:\s*21\.5px/)
    expect(rule(OC_CSS, '.oc-send-row-field')).toMatch(/align-items:\s*flex-start/)
  })

  it('centres a row, puts the words left and the buttons right', () => {
    expect(rule(OC_CSS, '.oc-send-row')).toMatch(/align-items:\s*center/)
    expect(rule(OC_CSS, '.oc-send-row > :not(.btn)')).toMatch(/order:\s*-1/)
    expect(rule(OC_CSS, '.oc-send-row > button.btn:first-of-type')).toMatch(/margin-left:\s*auto/)
  })

  it('never wraps a button label inside its fixed height', () => {
    const btn = rule(INDEX_CSS, '.btn')
    expect(btn).toMatch(/height:\s*36px/)
    expect(btn).toMatch(/white-space:\s*nowrap/)
  })

  it('sizes the ND2B effective date to the btn-sm beside it', () => {
    expect(rule(OC_CSS, '.oc-pc-items .date-input > input:first-child')).toMatch(/height:\s*30px/)
    expect(rule(INDEX_CSS, '.btn-sm') ?? '').not.toMatch(/height:\s*(?!30px)\d+px/)
  })
})

describe('where the controls render', () => {
  it('Data Verification: the badge and its Continue button share one action row', () => {
    wrap(<StageDataVerification data={{ ...BASE, signing_method: 'manual', data_checked_at: 'x' }}
                                reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    const btn = screen.getByRole('button', { name: 'Continue to Signing →' })
    const row = btn.closest('.oc-send-row')
    expect(row).not.toBeNull()
    expect(row).not.toHaveClass('oc-send-row-field')
    expect(row).toHaveTextContent('Checked')
  })

  it('Confirmation: Undo sits in an action bar with a note saying when to use it', () => {
    const filed = { ...BASE, manual_receipt: { caseNo: '1' }, applied_at: 'x',
      profile_changes: [], documents: [] }
    wrap(<StageConfirmation data={filed} reload={vi.fn()} can={ALL} />)
    const btn = screen.getByRole('button', { name: 'CR rejected it — undo profile update' })
    const bar = btn.closest('.action-bar')
    expect(bar).not.toBeNull()
    expect(btn.closest('.ab-actions')).not.toBeNull()
    expect(bar.querySelector('.ab-note')).toHaveTextContent(/rejected this filing/)
  })

  it('Confirmation: once undone, the bar carries the record and no button', () => {
    const undone = { ...BASE, manual_receipt: { caseNo: '1' }, applied_at: 'x', undone_at: 'y',
      profile_changes: [], documents: [] }
    wrap(<StageConfirmation data={undone} reload={vi.fn()} can={ALL} />)
    const note = screen.getByText(/Profile update undone/)
    expect(note.closest('.action-bar')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /undo profile update/ })).not.toBeInTheDocument()
  })

  it('ND2B card: Add officer sits in its own select-and-button row; Open profile is in the header', () => {
    const data = { ...BASE, form_code: 'Nd2b', officers: [
      ...BASE.officers,
      { officer_id: 'o2', role: 'director', party_type: 'individual', name: 'LEE New', pending: false },
    ], entries: [{ id: 'n1', kind: 'change', officer_id: 'o1', capacity: 'director',
      party: { name: 'CHAN Tai Man', profile_path: '/persons/p1' }, items: [] }] }
    wrap(<ParticularsChangeCard data={data} reload={vi.fn()} can={ALL} />)
    expect(screen.getByRole('button', { name: 'Add officer' }).closest('.oc-add-officer')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Open profile' }).closest('.oc-pc-hd')).not.toBeNull()
  })
})
