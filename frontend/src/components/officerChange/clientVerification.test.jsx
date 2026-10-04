// Client Verification after Jacqueline's feedback of 1 Oct 2026 (A1, A3, A6,
// A7, A8, B1, B3, BQ1).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import RulesPanel from './RulesPanel.jsx'
import AttachmentsCard from './AttachmentsCard.jsx'
import ChangesCard from './ChangesCard.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import CessationDrawer from './CessationDrawer.jsx'
import StageClientVerification from './StageClientVerification.jsx'

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn(); const upload = vi.fn()
const blob = vi.fn(() => Promise.resolve(new Blob(['%PDF'])))
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: vi.fn(), upload: (...a) => upload(...a), blob: (...a) => blob(...a), put: vi.fn(),
  },
}))
vi.mock('../case/PdfPreview.jsx', () => ({
  default: ({ pills }) => <div data-testid="pdf">{(pills || []).map(p => p.label).join(' | ')}</div>,
  usePdfBlob: () => ({ url: null, error: null }),
}))

const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }
const RULES = {
  blocking: false,
  lines: ['After these changes the company will have 2 directors (2 natural persons) and 1 secretary.',
          'Directors: CHAN Tai Man and LEE Ka Ho.',
          'A company secretary remains — Get Started HK Limited.'],
  board: { directors: [{ name: 'CHAN Tai Man' }, { name: 'LEE Ka Ho' }], secretaries: [] },
  checks: [
    { code: 'has_changes', ok: true, level: 'rule', text: 'There are changes to file.' },
    { code: 'dates_present', ok: false, level: 'notice', text: '1 change has no effective date yet.' },
    { code: 'natural_director', ok: true, level: 'rule', text: 'At least one director is a natural person.' },
  ],
}
const BASE = {
  id: 'k1', case_no: 'ND2A-2026-0007', form_code: 'Nd2a', case_type: 'ND2A', editable: true,
  officers: [{ officer_id: 'o1', role: 'director', party_type: 'individual', name: 'CHAN Tai Man' }],
  entries: [], documents: [], rules: RULES, problems: [], reply_by_default: '2026-10-07',
  route: { esign_available: true, reasons: [], consents: [] }, client_approved: null,
}
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ recipients: [], default_to: [] })
})

describe('RulesPanel — three lines (A6)', () => {
  it('reads as three lines, with notices behind "Show all checks"', async () => {
    const user = userEvent.setup()
    render(<RulesPanel rules={RULES} />)
    expect(screen.getByText('Directors: CHAN Tai Man and LEE Ka Ho.')).toBeInTheDocument()
    expect(screen.getByText('A company secretary remains — Get Started HK Limited.')).toBeInTheDocument()
    expect(screen.queryByText('There are changes to file.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show all checks (3)' }))
    expect(screen.getByText('There are changes to file.')).toBeInTheDocument()
  })

  it('always shows a breached rule', () => {
    const breach = { ...RULES, blocking: true, checks: [...RULES.checks, {
      code: 'has_secretary', ok: false, level: 'rule',
      text: 'The company would be left without a company secretary.' }] }
    render(<RulesPanel rules={breach} />)
    expect(screen.getByText('The company would be left without a company secretary.')).toBeInTheDocument()
  })
})

describe('No director would remain (A7)', () => {
  it('offers to close the case pending further instructions, reason pre-filled', async () => {
    const user = userEvent.setup()
    const rules = { ...RULES, blocking: true,
      lines: [RULES.lines[0], 'No director would remain.', RULES.lines[2]],
      board: { directors: [], secretaries: [{ name: 'Get Started HK Limited' }] },
      checks: [{ code: 'natural_director', ok: false, level: 'rule',
                 text: 'A private company must keep at least one director who is a natural person.' }] }
    wrap(<StageClientVerification data={{ ...BASE, rules, entries: [{ id: 'n1', kind: 'cessation',
      party: { name: 'CHAN Tai Man' }, summary: 'Director' }] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/does not file the director's resignation \(ND4\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close case — pending further instructions' }))
    expect(screen.getByLabelText(/Why is this case not proceeding/)).toHaveValue(
      'Pending further instructions — no director would remain after these changes. ' +
      'The client has been told they may file Form ND4 themselves.')
  })
})

describe('AttachmentsCard (A3)', () => {
  const DOCS = [{ id: 'd1', entry_id: null, file_name: 'resolution-signed.pdf', type_label: 'Board resolution',
    send_with_email: false, source: 'upload' }]

  it('uploads a document for the whole form, ticked to go with the email', async () => {
    upload.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    render(<AttachmentsCard data={{ ...BASE, documents: [] }} reload={vi.fn()} can={ALL} />)
    await user.upload(screen.getByLabelText('Choose file'), new File(['x'], 'memo.pdf'))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(upload).toHaveBeenCalled())
    const [path, form] = upload.mock.calls[0]
    expect(path).toBe('/officer-changes/k1/documents')
    expect(form.get('send_with_email')).toBe('true')
    expect(form.get('document_type_code')).toBe('board_resolution')
  })

  it('ticks an uploaded document to go with the email', async () => {
    patch.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    render(<AttachmentsCard data={{ ...BASE, documents: DOCS }} reload={vi.fn()} can={ALL} />)
    await user.click(screen.getByLabelText('Send resolution-signed.pdf with the email'))
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1/documents/d1', { send_with_email: true })
  })

  it('attaches the generated written resolution and previews it', async () => {
    patch.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    render(<AttachmentsCard data={{ ...BASE, documents: [] }} reload={vi.fn()} can={ALL} />)
    await user.click(screen.getByLabelText(/Attach the written resolution prepared by G-FlowDesk/))
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1', { attach_resolution: true })
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    expect(blob).toHaveBeenCalledWith('/officer-changes/k1/resolution')
  })

  it('is ND2A only for the resolution, and read-only without edit', () => {
    render(<AttachmentsCard data={{ ...BASE, form_code: 'Nd2b', documents: DOCS }} reload={vi.fn()}
                            can={{ ...ALL, write: false }} />)
    expect(screen.queryByText(/written resolution prepared by G-FlowDesk/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument()
    expect(screen.getByText('resolution-signed.pdf')).toBeInTheDocument()
  })
})

describe('Effective date is optional at send (A1)', () => {
  it('saves a cessation with no date and says when it will be asked for', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await user.selectOptions(screen.getByLabelText(/Officer/), 'o1')
    expect(screen.getByText(/Leave blank to fill in the most recent date at Signing/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add cessation' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1].effective_date).toBe('')
  })
})

describe('Consent line on the change list (A5, Levi 2026-10-05)', () => {
  it('says e-Sign or the manual route, and never offers an in-portal consent', () => {
    const entries = [
      { id: 'n1', kind: 'appointment', capacity: 'director', party: { name: 'LEE Ka Ho' },
        summary: 'Director', consent_mode: 'esign' },
      { id: 'n2', kind: 'appointment', capacity: 'director', party: { name: 'HO New' },
        summary: 'Director', consent_mode: 'manual' },
    ]
    wrap(<ChangesCard data={{ ...BASE, entries }} reload={vi.fn()} can={ALL} />)
    expect(screen.getByText(/Consent: e-Sign — PIN-signed from the e-Registry account on file/)).toBeInTheDocument()
    expect(screen.getByText(/Consent: manual route — given on the CR portal/)).toBeInTheDocument()
    expect(screen.queryByText(/G-FlowDesk from their email/)).not.toBeInTheDocument()
  })
})

describe('ND2B card (B1, B3)', () => {
  const OLD = { line1: '', line2: 'Harbour Vista', line3: '9 Model Road', city: 'NORTHPOINT', country: 'HK' }
  const NEW = { line1: 'Flat 20A', line2: 'Harbour Vista', line3: '9 Model Road', city: 'NORTHPOINT', country: 'HK' }
  const ND2B = { ...BASE, form_code: 'Nd2b', case_type: 'ND2B', anniversary_default: '2026-03-12',
    entries: [{ id: 'n1', kind: 'change', capacity: 'director', officer_id: 'o1',
      party: { name: 'CHAN Tai Man' }, items: [
        { key: 'residential_address', cr_item: 'd', label: 'Residential address', old: OLD, new: NEW,
          old_text: 'x', new_text: 'y', effective_date: '2026-03-12' }] }] }

  it('shows an address change in CR\'s five lines, with (blank) for an empty line', () => {
    wrap(<ParticularsChangeCard data={ND2B} reload={vi.fn()} can={ALL} />)
    expect(screen.getAllByText('Flat/Floor/Block etc.').length).toBeGreaterThan(0)
    expect(screen.getByText('(blank)')).toBeInTheDocument()
    expect(screen.getByText('Flat 20A')).toBeInTheDocument()
  })

  it('says the lines are dated the anniversary, matching the NAR1', () => {
    wrap(<ParticularsChangeCard data={ND2B} reload={vi.fn()} can={ALL} />)
    expect(screen.getByText(/Dated the anniversary, 12 Mar 2026, so this ND2B matches the NAR1/))
      .toBeInTheDocument()
  })
})

describe('Send card (A8) and the ND2B waiver (BQ1)', () => {
  it('tells the operator the client gets the full form with the PI sheets', () => {
    wrap(<StageClientVerification data={{ ...BASE, entries: [{ id: 'n1', kind: 'cessation',
      party: { name: 'CHAN Tai Man' }, summary: 'Director' }] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/including the protected-information sheets/)).toBeInTheDocument()
    expect(screen.getByTestId('pdf')).toHaveTextContent('Client copy — full form incl. PI')
  })

  it('lets an ND2B proceed without the client, with a reason', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<StageClientVerification data={{ ...BASE, form_code: 'Nd2b', case_type: 'ND2B',
      verification_sent_at: '2026-10-01T02:00:00Z', entries: [] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Proceed without confirmation' }))
    const dialog = screen.getByRole('dialog', { name: /Proceed without the client/ })
    expect(within(dialog).getByRole('button', { name: 'Proceed' })).toBeDisabled()
    await user.type(within(dialog).getByLabelText(/Why/), 'Deadline on 21 Sept; client away')
    await user.click(within(dialog).getByRole('button', { name: 'Proceed' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/verification/proceed',
      { reason: 'Deadline on 21 Sept; client away' }))
  })

  it('never offers the waiver on an ND2A', () => {
    wrap(<StageClientVerification data={{ ...BASE, verification_sent_at: '2026-10-01T02:00:00Z' }}
                                  reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Proceed without confirmation' })).not.toBeInTheDocument()
  })
})
