import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AddCompanyModal from './AddCompanyModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

const onClose = vi.fn()
const onCreated = vi.fn()
const renderModal = () => render(<AddCompanyModal onClose={onClose} onCreated={onCreated} />)

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  // the Country of Incorporation select reads /lookups
  api.get.mockResolvedValue({
    // CR's own Country & Region sheet. `lookup_values.country` is not used
    // for this field: 20 of its codes resolve to nothing CR accepts.
    cr_country: [{ code: 'GB', label: 'United Kingdom' }, { code: 'HK', label: 'Hong Kong' }],
    cr_company_type: [{ code: 'P', label: 'Private' }, { code: 'N', label: 'Public' },
                      { code: 'G', label: 'Limited by Guarantee' }],
  })
  api.post.mockResolvedValue({ id: 'new-1', company_name: 'NewCo' })
  api.put.mockResolvedValue({ id: 'addr-1' })
})

/** Company type is fetched, so it is not selectable on the first paint. */
async function selectCompanyType(user, code = 'P') {
  const select = screen.getByLabelText(/Company Type/)
  await waitFor(() =>
    expect(select.querySelector(`option[value="${code}"]`)).not.toBeNull())
  await user.selectOptions(select, code)
}

async function fillRequired(user) {
  await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
  await user.selectOptions(screen.getByLabelText(/Status/), 'pre_incorporation')
  await selectCompanyType(user)
  // The address is now the separate lines CR receives, not one free-text box.
  await user.type(screen.getByLabelText(/Flat \/ Floor \/ Block/), '1 Harbour View St')
  await user.type(screen.getByLabelText(/Company Phone/), '3500 1234')
}

describe('AddCompanyModal', () => {
  it('offers CRs three company types, not Viewpoints descriptions', async () => {
    // The list used to be three hardcoded free-text descriptions. CR takes
    // P, N or G on `coyType` and refuses anything else, so a company created
    // here was born with a value its own annual return could not carry.
    renderModal()
    await waitFor(() =>
      expect(within(screen.getByLabelText(/Company Type/)).queryAllByRole('option').length)
        .toBeGreaterThan(1))
    const options = within(screen.getByLabelText(/Company Type/))
      .queryAllByRole('option').map(o => o.textContent)

    expect(options).toEqual(['Select…', 'Private', 'Public', 'Limited by Guarantee'])
  })

  it('only offers Pre-Incorporation and Live at create time (OQ-3)', () => {
    renderModal()
    const options = within(screen.getByLabelText(/Status/)).queryAllByRole('option')
      .map(o => o.textContent)
    expect(options).toEqual(['Select…', 'Pre-Incorporation', 'Live'])
    expect(options).not.toContain('Ceased')
  })

  it('blocks submit and shows errors when required fields are missing', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('Company name is required')).toBeInTheDocument()
    expect(screen.getByText('Status is required')).toBeInTheDocument()
    expect(screen.getByText('Company type is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('validates BRN is 8 digits', async () => {
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.type(screen.getByLabelText('BRN'), '123')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('BRN must be 8 digits')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('creates the company and reports the new record back', async () => {
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/companies', {
        company_name: 'NewCo',
        status: 'pre_incorporation',
        company_type: 'P',
        incorporation_place: 'HK',
        company_phone: '+852 3500 1234',
      })
    })
    // The address goes through its own endpoint, so a company created here
    // meets the same validation as every later edit.
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(
        '/companies/new-1/registered-address',
        expect.objectContaining({ line1: '1 Harbour View St', country: 'HK' }),
      )
    })
    expect(onCreated).toHaveBeenCalledWith({ id: 'new-1', company_name: 'NewCo' })
  })

  it('surfaces a server error without closing', async () => {
    const user = userEvent.setup()
    api.post.mockRejectedValue(new Error('duplicate BRN'))
    renderModal()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('duplicate BRN')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('cancels without creating', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(api.post).not.toHaveBeenCalled()
  })
})

describe('AddCompanyModal — discard guard (UAT F-1)', () => {
  it('closes straight away when nothing has been entered', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.click(container.querySelector('.overlay'))
    expect(onClose).toHaveBeenCalled()
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument()
  })

  it('does not treat the auto-filled Hong Kong default as an edit', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await waitFor(() => expect(screen.getByLabelText(/Country of Incorporation/)).toHaveValue('HK'))
    await user.click(container.querySelector('.overlay'))
    expect(onClose).toHaveBeenCalled()
  })

  it('asks before discarding a filled form dismissed by backdrop click', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
    await user.click(container.querySelector('.overlay'))
    expect(await screen.findByText('Discard changes?')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps the entered data when the operator chooses Keep editing', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(await screen.findByRole('button', { name: 'Keep editing' }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Company Name/)).toHaveValue('NewCo')
  })

  it('closes when the operator confirms Discard', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('treats a changed country of incorporation as an edit worth guarding', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await waitFor(() => expect(screen.getByLabelText(/Country of Incorporation/)).toHaveValue('HK'))
    await user.selectOptions(screen.getByLabelText(/Country of Incorporation/), 'GB')
    await user.click(container.querySelector('.overlay'))
    expect(await screen.findByText('Discard changes?')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('AddCompanyModal — Hong Kong default (UAT F-2)', () => {
  it('preselects Hong Kong once the country vocabulary loads', async () => {
    renderModal()
    await waitFor(() => {
      expect(screen.getByLabelText(/Country of Incorporation/)).toHaveValue('HK')
    })
  })

  it('leaves the field blank when Hong Kong is absent from the vocabulary', async () => {
    api.get.mockResolvedValue({ cr_country: [{ code: 'GB', label: 'United Kingdom' }] })
    renderModal()
    await waitFor(() => {
      expect(within(screen.getByLabelText(/Country of Incorporation/)).getAllByRole('option'))
        .toHaveLength(2)
    })
    expect(screen.getByLabelText(/Country of Incorporation/)).toHaveValue('')
  })
})

describe('AddCompanyModal — dialling code (UAT F-3)', () => {
  it('defaults the dialling code to +852', () => {
    renderModal()
    expect(screen.getByLabelText('Dialling code')).toHaveValue('+852')
  })

  it('composes the dialling code and number into one phone string', async () => {
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.selectOptions(screen.getByLabelText('Dialling code'), '+65')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/companies',
        expect.objectContaining({ company_phone: '+65 3500 1234' }),
      )
    })
  })

  it('never posts the dialling code as its own field', async () => {
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(Object.keys(api.post.mock.calls[0][1])).not.toContain('phone_code')
    expect(Object.keys(api.post.mock.calls[0][1])).not.toContain('phone_number')
  })
})

describe('AddCompanyModal — required legend (UAT F-4)', () => {
  it('explains what the asterisk means', () => {
    renderModal()
    expect(screen.getByText(/Fields marked with an asterisk are required/)).toBeInTheDocument()
  })
})

describe('AddCompanyModal — newly required fields (UAT F-5)', () => {
  it('blocks submit when the registered address is empty', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
    await user.selectOptions(screen.getByLabelText(/Status/), 'pre_incorporation')
    await selectCompanyType(user)
    await user.type(screen.getByLabelText(/Company Phone/), '3500 1234')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('A registered address is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('blocks submit when only a dialling code was chosen and no number typed', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
    await user.selectOptions(screen.getByLabelText(/Status/), 'pre_incorporation')
    await selectCompanyType(user)
    await user.type(screen.getByLabelText(/Flat \/ Floor \/ Block/), '1 Harbour View St')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('Company phone is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('blocks submit when the country of incorporation is empty', async () => {
    const user = userEvent.setup()
    // Company type still has to be selectable — it comes from /lookups too.
    api.get.mockResolvedValue({
      cr_country: [{ code: 'GB', label: 'United Kingdom' }],
      cr_company_type: [{ code: 'P', label: 'Private' }],
    })
    renderModal()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Create Company' }))
    expect(await screen.findByText('Country of incorporation is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })
})

// ── Parity with the profile's edit form (Levi 2026-09-04, item 1) ────────────

describe('AddCompanyModal — every field the profile can edit', () => {
  beforeEach(() => {
    api.get.mockResolvedValue({
      cr_country: [{ code: 'HK', label: 'Hong Kong' }],
      cr_company_type: [{ code: 'P', label: 'Private' }],
      cr_business_nature: [{ code: '001', label: 'Crop and animal production' }],
    })
  })

  it('offers the six fields that used to be edit-only', async () => {
    // Creating a company from a client's own paperwork meant creating a
    // half-record, saving it, reopening it and typing the rest into a second
    // form with different labels — and three of these six (Chinese Name,
    // CR No., Incorporation Date) are on the certificate the operator is
    // reading from at the moment they press New Company.
    renderModal()
    for (const label of ['Chinese Name', 'CR No.', 'Incorporation Date',
                         'Business Nature', 'Mortgages and Charges', 'Case Notes']) {
      expect(await screen.findByLabelText(label)).toBeInTheDocument()
    }
  })

  it('posts them, and lets the backend derive the business-nature description', async () => {
    // CR derives `natureDesc` from `nature`, so the operator picks a code and
    // the description follows. A typed description could disagree with the
    // code it is supposed to describe.
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.type(screen.getByLabelText('Chinese Name'), '天際顧問')
    await user.type(screen.getByLabelText('CR No.'), '3300012')
    await user.type(screen.getByLabelText('Mortgages and Charges'), 'Nil')
    await waitFor(() => expect(
      screen.getByLabelText('Business Nature').querySelector('option[value="001"]'))
      .not.toBeNull())
    await user.selectOptions(screen.getByLabelText('Business Nature'), '001')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const body = api.post.mock.calls[0][1]
    expect(body.company_name_zh).toBe('天際顧問')
    expect(body.cr_number).toBe('3300012')
    expect(body.mortgages_total).toBe('Nil')
    expect(body.business_nature_code).toBe('001')
    expect(body).not.toHaveProperty('business_nature_desc')
  })

  it('still omits the optional fields that were left blank', async () => {
    const user = userEvent.setup()
    renderModal()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const body = api.post.mock.calls[0][1]
    expect(body).not.toHaveProperty('case_notes')
    expect(body).not.toHaveProperty('company_name_zh')
  })
})
