import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ReturnDataCard from './ReturnDataCard.jsx'

const get = vi.fn(); const patch = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: { get: (...a) => get(...a), patch: (...a) => patch(...a) },
}))

const DATA = {
  year: 2026,
  company_name: 'Harbour Tech Ltd.', company_name_zh: '海港科技有限公司',
  br_number: '2100028', cr_number: '3456789',
  incorporation_date: '2022-01-01',
  registered_office: 'Unit 12A, Central, Hong Kong',
  directors: ['Chan Tai Man', 'Nominee Holdings Ltd.'],
  secretaries: ['Get Started HK Limited'],
  signatory: { name: 'Wong Mei Ling', capacity: 'Company Secretary',
               person_id: 'T2607S', is_corporate: false },
  signatory_capacity: null,
  signatory_capacity_options: [
    'Authorized Person', 'Authorized Representative', 'Company Secretary',
    'Director', 'Reserve Director',
  ],
  member_count: 2,
  share_classes: [{ name: 'Ordinary', total_issued: 100, currency: 'HKD' }],
  problems: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(DATA)
  patch.mockResolvedValue({})
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
    expect(await screen.findByText('Wong Mei Ling')).toBeInTheDocument()
  })

  it('says so plainly when there is no eligible signatory', async () => {
    get.mockResolvedValue({ ...DATA, signatory: null })
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByText('No eligible signatory on record'))
      .toBeInTheDocument()
  })

  it('distinguishes a missing field from an empty one', async () => {
    get.mockResolvedValue({ ...DATA, registered_office: null, directors: [] })
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')
    // "Not on record" is an answer; a blank cell is not.
    expect(screen.getAllByText('Not on record').length).toBeGreaterThanOrEqual(2)
  })

  // Levi 2026-08-30. This card no longer pre-judges the company: `problems`
  // used to render as a red "This company cannot be filed as a NAR1 yet" panel
  // before anyone had pressed anything, and every real GSHK client tripped it.
  // Faults now come from CR, when CR is actually asked.
  it('does NOT block the company before CR has been asked', async () => {
    get.mockResolvedValue({
      ...DATA,
      problems: ['registered office: no address on record',
                 'signatory: Get Started HK Limited is a body corporate'],
    })
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')

    expect(screen.queryByText(/cannot be filed as a NAR1/)).not.toBeInTheDocument()
    expect(screen.queryByText('registered office: no address on record'))
      .not.toBeInTheDocument()
    // The data is still all there — that never depended on the verdict.
    expect(screen.getByText('2100028')).toBeInTheDocument()
  })

  // ---- the signing capacity picker ----------------------------------------
  //
  // The one field the portal cannot derive: a body-corporate secretary signs
  // through a natural person and CR's vocabulary says which one.

  it('offers CR\'s capacity vocabulary for this signatory', async () => {
    render(<ReturnDataCard caseId="c1" />)
    const select = await screen.findByLabelText('Signing capacity')
    const values = [...select.options].map(o => o.value)
    expect(values).toEqual(
      ['', 'Authorized Person', 'Authorized Representative', 'Company Secretary',
       'Director', 'Reserve Director'])
  })

  it('starts unchosen rather than defaulting to a capacity nobody picked', async () => {
    // A wrong capacity is accepted by CR's schema and rejected server-side
    // AFTER the fee, so a plausible-looking default is worse than a blank.
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByLabelText('Signing capacity')).toHaveValue('')
  })

  it('saves the chosen capacity to the case', async () => {
    const user = userEvent.setup()
    render(<ReturnDataCard caseId="c1" />)
    const select = await screen.findByLabelText('Signing capacity')
    await user.selectOptions(select, 'Director')
    await waitFor(() => expect(patch).toHaveBeenCalledWith(
      '/cases/c1', { signatory_capacity: 'Director' }))
  })

  it('re-reads the return after saving, because the capacity feeds the mapper', async () => {
    const user = userEvent.setup()
    render(<ReturnDataCard caseId="c1" />)
    const select = await screen.findByLabelText('Signing capacity')
    get.mockClear()
    await user.selectOptions(select, 'Director')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/cases/c1/return-data'))
  })

  it('shows a stored capacity rather than asking again', async () => {
    get.mockResolvedValue({ ...DATA, signatory_capacity: 'Company Secretary' })
    render(<ReturnDataCard caseId="c1" />)
    expect(await screen.findByLabelText('Signing capacity'))
      .toHaveValue('Company Secretary')
  })

  it('keeps the card standing when the save fails', async () => {
    // A failed save must not replace the return the operator was reading.
    const user = userEvent.setup()
    patch.mockRejectedValue(new Error('nope'))
    render(<ReturnDataCard caseId="c1" />)
    const select = await screen.findByLabelText('Signing capacity')
    await user.selectOptions(select, 'Director')
    await waitFor(() => expect(screen.getByText(/nope/)).toBeInTheDocument())
    expect(screen.getByText('2100028')).toBeInTheDocument()
  })

  it('offers no picker at all when there is no signatory to describe', async () => {
    get.mockResolvedValue({
      ...DATA, signatory: null, signatory_capacity_options: [],
    })
    render(<ReturnDataCard caseId="c1" />)
    await screen.findByText('NAR1 return data')
    expect(screen.queryByLabelText('Signing capacity')).not.toBeInTheDocument()
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
