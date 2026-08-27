import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ReturnDataCard from './ReturnDataCard.jsx'

const get = vi.fn()
vi.mock('../../lib/api.js', () => ({ api: { get: (...a) => get(...a) } }))

const DATA = {
  year: 2026,
  company_name: 'Harbour Tech Ltd.', company_name_zh: '海港科技有限公司',
  br_number: '2100028', cr_number: '3456789',
  incorporation_date: '2022-01-01',
  registered_office: 'Unit 12A, Central, Hong Kong',
  directors: ['Chan Tai Man', 'Nominee Holdings Ltd.'],
  secretaries: ['Get Started HK Limited'],
  signatory: { name: 'Wong Mei Ling', capacity: 'Company Secretary',
               person_id: 'T2607S' },
  member_count: 2,
  share_classes: [{ name: 'Ordinary', total_issued: 100, currency: 'HKD' }],
  problems: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(DATA)
})

describe('ReturnDataCard', () => {
  it('reads the return for the case in the route', async () => {
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')
    expect(get).toHaveBeenCalledWith('/cases/c1/return-data')
  })

  it('shows the return the Companies Registry will be sent', async () => {
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')

    expect(screen.getByText(/Harbour Tech Ltd\./)).toBeInTheDocument()
    expect(screen.getByText('2100028')).toBeInTheDocument()
    expect(screen.getByText('Unit 12A, Central, Hong Kong')).toBeInTheDocument()
    expect(screen.getByText('Chan Tai Man · Nominee Holdings Ltd.')).toBeInTheDocument()
    expect(screen.getByText('Get Started HK Limited')).toBeInTheDocument()
    expect(screen.getByText('2 members · 100 Ordinary')).toBeInTheDocument()
    expect(screen.getByText('1 (Ordinary)')).toBeInTheDocument()
  })

  it('names the signatory — the commonest reason a NAR1 cannot be filed', async () => {
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByText('Wong Mei Ling (Company Secretary)'))
      .toBeInTheDocument()
  })

  it('says so plainly when there is no eligible signatory', async () => {
    get.mockResolvedValue({ ...DATA, signatory: null })
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByText('No eligible signatory — see below'))
      .toBeInTheDocument()
  })

  it('distinguishes a missing field from an empty one', async () => {
    get.mockResolvedValue({ ...DATA, registered_office: null, directors: [] })
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')
    // "Not on record" is an answer; a blank cell is not.
    expect(screen.getAllByText('Not on record').length).toBeGreaterThanOrEqual(2)
  })

  it('lists every mapper problem as a readable sentence', async () => {
    get.mockResolvedValue({
      ...DATA,
      problems: ['registered office: no address on record',
                 'signatory: Get Started HK Limited is a body corporate'],
    })
    render(<ReturnDataCard caseId="c1" />)

    expect(await screen.findByText('registered office: no address on record'))
      .toBeInTheDocument()
    expect(screen.getByText(/is a body corporate/)).toBeInTheDocument()
    // The card still shows the DATA — this is the case it is most needed in.
    expect(screen.getByText('2100028')).toBeInTheDocument()
  })

  it('never renders an object as text', async () => {
    // React error #31 blanks the whole tree, and a CR fault arrives as a
    // [severity, message] PAIR rather than a string.
    get.mockResolvedValue({
      ...DATA,
      problems: [['E', 'Please input valid District.']],
    })
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')
    expect(screen.getByText(/Please input valid District/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('[object Object]')
  })

  it('reports a failed read instead of rendering an empty return', async () => {
    get.mockRejectedValue(new Error('boom'))
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByText(/Could not read this company's return data/))
      .toBeInTheDocument()
  })

  it('re-reads when the case changes underneath it', async () => {
    const { rerender } = render(<ReturnDataCard caseId="c1" reloadKey="t1" />)
    await screen.findByText('NAR1 return data')
    expect(get).toHaveBeenCalledTimes(1)

    rerender(<ReturnDataCard caseId="c1" reloadKey="t2" />)
    await screen.findByText('NAR1 return data')
    expect(get).toHaveBeenCalledTimes(2)
  })
})
