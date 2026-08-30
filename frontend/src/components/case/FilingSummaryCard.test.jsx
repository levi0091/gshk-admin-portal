import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import FilingSummaryCard from './FilingSummaryCard.jsx'

const get = vi.fn()
vi.mock('../../lib/api.js', () => ({ api: { get: (...a) => get(...a) } }))

const SUMMARY = {
  form_code: 'Nar1', stage: 'signed', has_schedule_1: true,
  company_name: 'Harbour Tech Ltd.', br_number: '2100028', year: '2026',
  registered_office: 'Unit 12A, Central, HKG',
  directors: ['CHAN, TAI MAN'], secretaries: ['Get Started HK Limited'],
  share_classes: [{ name: 'Ordinary', currency: 'HKD', total_issued: '100' }],
  member_count: 2,
  signatory: { name: 'CHAN, TAI MAN', capacity: 'Director', date: '27/08/2026' },
  signed_at: '2026-08-27T06:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(SUMMARY)
})

describe('FilingSummaryCard', () => {
  it('reads the FILING, not the company profile', async () => {
    // The distinction is the whole point: the profile can have moved since
    // validation, and what gets filed is the snapshot.
    render(<FilingSummaryCard filingId="f1" />)
    await screen.findByText(/Final summary/)
    expect(get).toHaveBeenCalledWith('/tpsi/filings/f1/summary')
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('shows what is about to be filed', async () => {
    render(<FilingSummaryCard filingId="f1" />)
    await screen.findByText(/Final summary/)

    expect(screen.getByText('NAR1 · Annual Return + Schedule 1')).toBeInTheDocument()
    expect(screen.getByText('Harbour Tech Ltd. (BRN 2100028)')).toBeInTheDocument()
    expect(screen.getByText('Unit 12A, Central, HKG')).toBeInTheDocument()
    expect(screen.getByText('2 members · 100 Ordinary')).toBeInTheDocument()
    expect(screen.getByText('✓ Signed — CHAN, TAI MAN (Director) · 27/08/2026'))
      .toBeInTheDocument()
  })

  it('never shows the presenter or deposit account number', async () => {
    // Those stay a super-admin-only field (routers/tpsi.py _deposit_account).
    // An ordinary filer sees the balance, not the account.
    get.mockResolvedValue({ ...SUMMARY, account_no: 'N00108070000',
                            presenter: 'T260727100116D' })
    render(<FilingSummaryCard filingId="f1" />)
    await screen.findByText(/Final summary/)

    expect(document.body.textContent).not.toContain('N00108070000')
    expect(document.body.textContent).not.toContain('T260727100116D')
    // "not" sits in its own <b>, so match a contiguous run.
    expect(screen.getByText(/GSHK's presenter deposit account/)).toBeInTheDocument()
  })

  it('does not claim a signature the filing does not have', async () => {
    get.mockResolvedValue({ ...SUMMARY, signed_at: null })
    render(<FilingSummaryCard filingId="f1" />)
    await screen.findByText(/Final summary/)
    expect(screen.getByText('CHAN, TAI MAN (Director) · 27/08/2026')).toBeInTheDocument()
    expect(screen.queryByText(/✓ Signed/)).not.toBeInTheDocument()
  })

  it('tells the operator NOT to file when the summary cannot be read', async () => {
    // A blank summary in front of an irreversible charge is worse than an
    // error that says so.
    get.mockRejectedValue(new Error('filing XML could not be parsed'))
    render(<FilingSummaryCard filingId="f1" />)
    expect(await screen.findByText(/Do not file until this shows the return/))
      .toBeInTheDocument()
  })

  it('renders nothing at all without a filing', () => {
    const { container } = render(<FilingSummaryCard filingId={null} />)
    expect(container).toBeEmptyDOMElement()
    expect(get).not.toHaveBeenCalled()
  })
})
