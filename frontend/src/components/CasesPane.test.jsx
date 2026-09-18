import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import CasesPane, { caseSummary, orderedCases, stageOf } from './CasesPane.jsx'

// Rows in the shape GET /companies/{id} really sends: `nar1_case_registry`
// plus `return_year`, and `workflow_status` as the dashboard's badge object.
// One carries the view's BARE code string, which is what the endpoint sent
// before it was aligned with the dashboard — both must render.
const signing = {
  id: 'c-sign', case_no: 'NAR-2026-0064', ar_period_year: null, return_year: 2026,
  workflow_status: { code: 'signing', label: 'Signing', off_portal: false, cr_text: null },
  created_by_name: 'Levi Z.', created_at: '2026-08-31T08:19:50.065998+00:00',
  updated_at: '2026-09-07T03:41:55.59277+00:00',
}
const awaiting = {
  id: 'c-wait', case_no: 'NAR-2026-0070', ar_period_year: 2025, return_year: 2025,
  workflow_status: 'awaiting_client',
  created_by_name: 'UAT Shot', created_at: '2026-09-08T08:58:05+00:00',
  updated_at: '2026-09-09T01:03:47+00:00',
}
const noYear = {
  id: 'c-new', case_no: 'NAR-2026-0081', ar_period_year: null, return_year: null,
  workflow_status: { code: 'client_verification', label: 'Client Verification' },
  created_by_name: 'roy', created_at: '2026-09-18T08:56:41+00:00',
  updated_at: '2026-09-18T08:56:41+00:00',
}
const registered = {
  id: 'c-reg', case_no: 'NAR-2025-0031', ar_period_year: 2024, return_year: 2024,
  workflow_status: { code: 'cr_registered', label: 'Registered by CR', cr_text: 'Registered' },
  created_by_name: 'Levi Z.', created_at: '2025-03-01T02:00:00+00:00',
  updated_at: '2025-03-19T02:00:00+00:00',
}
const closed = {
  id: 'c-closed', case_no: 'NAR-2026-0080', ar_period_year: 2023, return_year: 2023,
  workflow_status: { code: 'closed', label: 'Closed' },
  created_by_name: 'Levi Z.', created_at: '2026-09-18T08:09:15+00:00',
  updated_at: '2026-09-18T16:56:14+00:00', closed_at: '2026-09-18T16:56:14+00:00',
  closed_by_name: 'Levi Z.', closed_reason: 'Opened for the wrong year',
}

const cardFor = caseNo => screen.getByText(caseNo).closest('article')
const headerOf = caseNo => within(cardFor(caseNo)).getAllByRole('button')[0]

describe('CasesPane', () => {
  it('says so when the company has no cases', () => {
    render(<CasesPane cases={{ nar1: [], nnc1: [] }} />)
    expect(screen.getByText('No cases yet.')).toBeInTheDocument()
  })

  it('heads each case with its return year, its case number and its status', () => {
    render(<CasesPane cases={{ nar1: [signing, awaiting], nnc1: [] }} />)

    const sign = cardFor('NAR-2026-0064')
    expect(within(sign).getByText('2026')).toBeInTheDocument()
    expect(within(sign).getByText('Signing')).toBeInTheDocument()
    // A bare code string is labelled from the local map, not printed raw.
    const wait = cardFor('NAR-2026-0070')
    expect(within(wait).getByText('2025')).toBeInTheDocument()
    expect(within(wait).getByText('Awaiting Client')).toBeInTheDocument()
  })

  it('shows the resolved year for a legacy case whose stored year is empty', () => {
    render(<CasesPane cases={{ nar1: [signing] }} />)
    expect(within(cardFor('NAR-2026-0064')).getByText('2026')).toBeInTheDocument()
  })

  it('says a year has not been chosen rather than leaving the spine blank', () => {
    render(<CasesPane cases={{ nar1: [noYear] }} />)
    expect(within(cardFor('NAR-2026-0081')).getByText(/not set/i)).toBeInTheDocument()
  })

  it('expands live cases with who created them and when they last moved', () => {
    render(<CasesPane cases={{ nar1: [signing] }} />)
    const card = cardFor('NAR-2026-0064')

    expect(headerOf('NAR-2026-0064')).toHaveAttribute('aria-expanded', 'true')
    expect(within(card).getByText('Created')).toBeInTheDocument()
    expect(within(card).getByText('31 Aug 2026')).toBeInTheDocument()
    expect(within(card).getByText(/Levi Z\./)).toBeInTheDocument()
    // Hong Kong wall-clock: 03:41 UTC is 11:41 in Hong Kong. ("Sept" or
    // "Sep" depending on the ICU build — that is format.js's business.)
    expect(within(card).getByText(/07 Sept? 2026.*11:41/)).toBeInTheDocument()
  })

  it('collapses finished cases — registered by CR, or closed', () => {
    render(<CasesPane cases={{ nar1: [registered, closed, signing] }} />)

    expect(headerOf('NAR-2025-0031')).toHaveAttribute('aria-expanded', 'false')
    expect(headerOf('NAR-2026-0080')).toHaveAttribute('aria-expanded', 'false')
    expect(within(cardFor('NAR-2025-0031')).queryByText('Created')).not.toBeInTheDocument()
    // The status still reads while collapsed.
    expect(within(cardFor('NAR-2025-0031')).getByText('Registered by CR')).toBeInTheDocument()
  })

  it('keeps a client rejection open — somebody has to act on it', () => {
    const rejected = { ...awaiting, workflow_status: 'client_rejected' }
    render(<CasesPane cases={{ nar1: [rejected] }} />)
    expect(headerOf('NAR-2026-0070')).toHaveAttribute('aria-expanded', 'true')
  })

  it('opens a finished case on click, and says why it was closed', async () => {
    const user = userEvent.setup()
    render(<CasesPane cases={{ nar1: [closed] }} />)

    await user.click(headerOf('NAR-2026-0080'))

    expect(headerOf('NAR-2026-0080')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Opened for the wrong year')).toBeInTheDocument()
  })

  it('folds a live case away on click without navigating', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    render(<CasesPane cases={{ nar1: [signing] }} onOpen={onOpen} />)

    await user.click(headerOf('NAR-2026-0064'))

    expect(headerOf('NAR-2026-0064')).toHaveAttribute('aria-expanded', 'false')
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('goes to the case from Open case', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    render(<CasesPane cases={{ nar1: [signing] }} onOpen={onOpen} />)

    await user.click(screen.getByRole('button', { name: /Open case/ }))

    expect(onOpen).toHaveBeenCalledWith('c-sign')
  })

  it('draws where the case is on the six stages', () => {
    render(<CasesPane cases={{ nar1: [signing] }} />)
    expect(screen.getByRole('img', { name: 'Stage 3 of 6: Signing' })).toBeInTheDocument()
  })

  it('separates in-progress from finished only when there are both', () => {
    const { unmount } = render(<CasesPane cases={{ nar1: [signing, closed] }} />)
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.getByText('Finished')).toBeInTheDocument()
    unmount()

    render(<CasesPane cases={{ nar1: [signing] }} />)
    expect(screen.queryByText('In progress')).not.toBeInTheDocument()
  })
})

describe('orderedCases', () => {
  it('puts in-progress first, then the newest return year, undecided years on top', () => {
    const ids = orderedCases({ nar1: [registered, awaiting, closed, signing, noYear] })
      .map(r => r.id)
    expect(ids).toEqual(['c-new', 'c-sign', 'c-wait', 'c-reg', 'c-closed'])
  })
})

describe('stageOf', () => {
  it.each([
    ['client_verification', 1, 'act'],
    ['awaiting_client', 1, 'info'],
    ['client_rejected', 1, 'bad'],
    ['data_verification', 2, 'act'],
    ['signing', 3, 'act'],
    ['submission', 4, 'act'],
    // Stage 6 takes CR's tone from the stepper's own table.
    ['cr_not_checked', 6, 'wait'],
    ['cr_pending', 6, 'info'],
    ['cr_approved', 6, 'warn'],
    ['cr_registered', 6, 'ok'],
    ['cr_rejected', 6, 'bad'],
    ['cr_unknown', 6, 'wait'],
  ])('%s is stage %i, tone %s', (code, stage, tone) => {
    expect(stageOf(code)).toEqual({ stage, tone })
  })

  it('gives a closed case no position — it stopped wherever it stopped', () => {
    expect(stageOf('closed')).toBeNull()
  })
})

describe('caseSummary', () => {
  it('counts what is in progress and what is finished', () => {
    expect(caseSummary({ nar1: [signing, awaiting, closed] })).toBe('2 in progress · 1 finished')
    expect(caseSummary({ nar1: [signing] })).toBe('1 in progress')
    expect(caseSummary({ nar1: [] })).toBeNull()
  })
})
