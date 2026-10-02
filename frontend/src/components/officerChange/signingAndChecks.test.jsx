// Data Verification, Signing and Submission after Jacqueline's feedback
// (A1, A4, AQ3, N1).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ManualChecks from './ManualChecks.jsx'
import EffectiveDatesPanel from './EffectiveDatesPanel.jsx'
import StageDataVerification from './StageDataVerification.jsx'
import StageSigning from './StageSigning.jsx'
import StageSubmission from './StageSubmission.jsx'
import { stageIndexFor } from './workflow.js'

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn(); const upload = vi.fn()
const put = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: vi.fn(), upload: (...a) => upload(...a), put: (...a) => put(...a),
    blob: vi.fn(() => Promise.resolve(new Blob())),
  },
}))
vi.mock('../case/PdfPreview.jsx', () => ({
  default: () => <div data-testid="pdf" />, usePdfBlob: () => ({ url: null, error: null }),
}))

const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }
const CHECKS = [
  { code: 'kyc', entry_id: 'n2', label: 'KYC / WorldCheck cleared — LEE Ka Ho', kind: 'tick',
    document_type: null, ok: true, document: null },
  { code: 'resignation_letter', entry_id: 'n1', label: 'Resignation letter on file — WONG Mei Ling',
    kind: 'document', document_type: 'resignation_letter', ok: true,
    document: { id: 'd1', file_name: 'resignation-letter-wong-mei-ling.pdf', uploaded_at: '2026-09-15T02:00:00Z' } },
  { code: 'written_resolution', entry_id: null, label: 'Signed written resolution on file',
    kind: 'document', document_type: 'board_resolution', ok: false, document: null },
]
const ENTRIES = [
  { id: 'n1', kind: 'cessation', capacity: 'director', party: { name: 'WONG Mei Ling' },
    summary: 'Director · ceases', documents: [], date_deferred: false, effective_date: '2026-09-12' },
  { id: 'n2', kind: 'appointment', capacity: 'director', party: { name: 'LEE Ka Ho' },
    summary: 'Director · appointed', documents: [], date_deferred: true, effective_date: null,
    eservice: { configured: true, has_password: true, eservice_user_id: 'LKH20455' } },
]
const BASE = {
  id: 'k1', case_no: 'ND2A-2026-0007', form_code: 'Nd2a', case_type: 'ND2A', client_approved: true,
  entries: ENTRIES, manual_checks: CHECKS, dates_missing: [], documents: [],
  route: { esign_available: true, reasons: [], consents: [], default: 'esign' },
  signatory: { name: 'Get Started HK Limited', capacities: ['Director'], default_capacity: 'Director' },
  verification_sent_at: '2026-10-01T00:00:00Z',
}
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({}) })

describe('ManualChecks (A4, the mock-up on p. 25)', () => {
  it('lists every check, ticked when done, with the attached file', () => {
    wrap(<ManualChecks data={BASE} reload={vi.fn()} can={ALL} />)
    expect(screen.getByText('KYC / WorldCheck cleared — LEE Ka Ho')).toBeInTheDocument()
    expect(screen.getByText('resignation-letter-wong-mei-ling.pdf')).toBeInTheDocument()
    const open = screen.getByText('Signed written resolution on file').closest('[data-check]')
    expect(open).toHaveAttribute('data-ok', 'false')
  })

  it('attaches the written resolution to the case, and replaces a letter on its entry', async () => {
    upload.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<ManualChecks data={BASE} reload={vi.fn()} can={ALL} />)
    await user.upload(screen.getByLabelText('Attach a file for Signed written resolution on file'),
      new File(['x'], 'resolution.pdf'))
    await waitFor(() => expect(upload).toHaveBeenCalled())
    expect(upload.mock.calls[0][0]).toBe('/officer-changes/k1/documents')
    expect(upload.mock.calls[0][1].get('document_type_code')).toBe('board_resolution')
    await user.upload(screen.getByLabelText('Replace the file for Resignation letter on file — WONG Mei Ling'),
      new File(['x'], 'letter2.pdf'))
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    expect(upload.mock.calls[1][0]).toBe('/officer-changes/k1/entries/n1/documents')
  })

  it('ticks KYC', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<ManualChecks data={BASE} reload={vi.fn()} can={ALL} />)
    await user.click(screen.getByLabelText('KYC / WorldCheck cleared — LEE Ka Ho'))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries/n2/kyc', { cleared: false })
  })

  it('draws no control without officer changes (edit)', () => {
    wrap(<ManualChecks data={BASE} reload={vi.fn()} can={{ ...ALL, write: false }} />)
    expect(screen.queryByLabelText(/Attach a file/)).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})

describe('Data Verification gate (A4) and the e-Sign route with a deferred date (A1)', () => {
  it('will not validate while a check is open, and says which', () => {
    wrap(<StageDataVerification data={{ ...BASE, signing_method: 'esign' }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Validate with CR Portal' })).toBeDisabled()
    expect(screen.getByText(/Finish the manual checks first: Signed written resolution on file/)).toBeInTheDocument()
  })

  it('with a date still blank, e-Sign continues to Signing without CR', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    const ready = CHECKS.map(c => ({ ...c, ok: true }))
    wrap(<StageDataVerification data={{ ...BASE, signing_method: 'esign', manual_checks: ready,
      dates_missing: ['LEE Ka Ho'] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Validate with CR Portal' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Continue to Signing' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/mark-checked', { signing_method: 'esign' })
  })

  it('no longer offers option A / option B wording for consents', () => {
    wrap(<StageDataVerification data={BASE} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByText(/option A|option B/)).not.toBeInTheDocument()
  })
})

describe('EffectiveDatesPanel (A1)', () => {
  it('asks for each deferred date and saves it', async () => {
    put.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<EffectiveDatesPanel data={{ ...BASE, dates_missing: ['LEE Ka Ho'] }} reload={vi.fn()} can={ALL} />)
    expect(screen.getByText(/The client was told these dates would be confirmed when GSHK files/))
      .toBeInTheDocument()
    const input = screen.getByLabelText('Effective date — LEE Ka Ho')
    await user.type(input, '2026-10-01')
    await user.click(screen.getByRole('button', { name: 'Save dates' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/officer-changes/k1/entries/n2/effective-date',
      { effective_date: '2026-10-01' }))
  })

  it('renders nothing when no date was deferred', () => {
    const { container } = wrap(<EffectiveDatesPanel
      data={{ ...BASE, entries: [ENTRIES[0]] }} reload={vi.fn()} can={ALL} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Signing with deferred dates (A1) and a stale e-Registry account (N1)', () => {
  it('paper: upload waits for the dates', () => {
    wrap(<StageSigning data={{ ...BASE, signing_method: 'manual', data_checked_at: 'x',
      dates_missing: ['LEE Ka Ho'] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByLabelText('Effective date — LEE Ka Ho')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload signed form' })).toBeDisabled()
  })

  it('e-Sign: validates with CR at Signing, then signs', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const user = userEvent.setup()
    wrap(<StageSigning data={{ ...BASE, signing_method: 'esign', data_checked_at: 'x' }}
                       reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Apply signatures' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Validate with CR' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/validate', {})
  })

  it('warns when an e-Registry account was opened with an old document', () => {
    wrap(<StageSigning data={{ ...BASE, signing_method: 'esign', filing: { stage: 'validated' },
      route: { ...BASE.route, consents: [{ entry_id: 'n2', signer_name: 'LEE Ka Ho', ready: true,
        id_mismatch: "LEE Ka Ho's e-Registry account was opened with passport X123…" }] } }}
                       reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/opened with passport X123/)).toBeInTheDocument()
  })
})

describe('Submission names the other open filings (AQ3)', () => {
  it('shows the alert above the filing', () => {
    wrap(<StageSubmission data={{ ...BASE, filing: { stage: 'signed' }, signing_method: 'esign',
      other_open_cases: [{ id: 'c9', case_no: 'NAR-2026-0042', case_type: 'NAR1', form_code: 'Nar1',
        workflow_status: { label: 'Awaiting client' } }] }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('link', { name: /NAR-2026-0042/ })).toBeInTheDocument()
  })
})

describe('workflow', () => {
  it('an e-Sign case marked checked has reached Signing before CR validates it', () => {
    expect(stageIndexFor({ client_approved: true, signing_method: 'esign', data_checked_at: 'x' })).toBe(3)
    expect(stageIndexFor({ client_approved: true, signing_method: 'esign' })).toBe(2)
  })
})
