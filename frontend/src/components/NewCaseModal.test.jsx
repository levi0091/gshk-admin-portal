import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import NewCaseModal from './NewCaseModal.jsx'

const get = vi.fn(); const post = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a) },
}))

const onClose = vi.fn(); const onCreated = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ companies: [
    { id: 'e1', company_name: 'Harbour Tech Ltd.', br_number: '2100028' },
  ] })
  post.mockResolvedValue({ id: 'c9', case_no: 'NAR-2026-0009' })
})

describe('NewCaseModal — from the dashboard (no company yet)', () => {
  const renderIt = () =>
    render(<NewCaseModal onClose={onClose} onCreated={onCreated} />)

  it('will not open a case until a company is chosen', () => {
    renderIt()
    expect(screen.getByRole('button', { name: 'Open case' })).toBeDisabled()
  })

  it('searches the registry and opens a case for the company picked', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.type(screen.getByLabelText('Company'), 'harbour')
    await user.click(await screen.findByText('Harbour Tech Ltd.'))
    await user.click(screen.getByRole('button', { name: 'Open case' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/cases', {
      entity_id: 'e1', form_code: 'Nar1',
    }))
    expect(onCreated).toHaveBeenCalledWith({ id: 'c9', case_no: 'NAR-2026-0009' })
  })

  it('says NNC1 is not available rather than offering a dead choice', () => {
    renderIt()
    expect(screen.getByText(/NNC1 \(incorporation\) cases are not available yet/))
      .toBeInTheDocument()
  })

  it('lists every reason the backend refused, not just the first', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(
      new Error('entity cannot be filed as a NAR1'),
      { status: 400, problems: ['no company secretary on record', 'no registered office'] },
    ))
    renderIt()
    await user.type(screen.getByLabelText('Company'), 'harbour')
    await user.click(await screen.findByText('Harbour Tech Ltd.'))
    await user.click(screen.getByRole('button', { name: 'Open case' }))

    expect(await screen.findByText('no company secretary on record')).toBeInTheDocument()
    expect(screen.getByText('no registered office')).toBeInTheDocument()
  })
})

describe('NewCaseModal — from a company profile', () => {
  const entity = { id: 'e7', company_name: 'Obsydian Group Limited' }

  it('fixes the company and does not make you search for it again', async () => {
    const user = userEvent.setup()
    render(<NewCaseModal entity={entity} onClose={onClose} onCreated={onCreated} />)

    expect(screen.getByText('Obsydian Group Limited')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Search by name or BRN')).not.toBeInTheDocument()
    expect(get).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Open case' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/cases', {
      entity_id: 'e7', form_code: 'Nar1',
    }))
  })

  it('is immediately ready — the company is already known', () => {
    render(<NewCaseModal entity={entity} onClose={onClose} onCreated={onCreated} />)
    expect(screen.getByRole('button', { name: 'Open case' })).toBeEnabled()
  })
})
