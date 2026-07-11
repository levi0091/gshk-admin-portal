import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AddCompanyModal from './AddCompanyModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { post: vi.fn() } }))
import { api } from '../lib/api.js'

const onClose = vi.fn()
const onCreated = vi.fn()
const renderModal = () => render(<AddCompanyModal onClose={onClose} onCreated={onCreated} />)

beforeEach(() => {
  vi.clearAllMocks()
  api.post.mockResolvedValue({ id: 'new-1', company_name: 'NewCo' })
})

async function fillRequired(user) {
  await user.type(screen.getByLabelText(/Company Name/), 'NewCo')
  await user.selectOptions(screen.getByLabelText(/Status/), 'pre_incorporation')
  await user.selectOptions(screen.getByLabelText(/Company Type/), 'Private company limited by shares')
}

describe('AddCompanyModal', () => {
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
    await user.type(screen.getByLabelText('Registered Address'), '1 Harbour View St')
    await user.type(screen.getByLabelText('Company Phone'), '+852 3500 1234')
    await user.click(screen.getByRole('button', { name: 'Create Company' }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/companies', {
        company_name: 'NewCo',
        status: 'pre_incorporation',
        company_type: 'Private company limited by shares',
        registered_address: '1 Harbour View St',
        company_phone: '+852 3500 1234',
      })
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
