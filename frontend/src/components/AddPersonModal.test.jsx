import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AddPersonModal from './AddPersonModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { post: vi.fn(), get: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

const onClose = vi.fn()
const onCreated = vi.fn()
const renderModal = () => render(<AddPersonModal onClose={onClose} onCreated={onCreated} />)

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  api.get.mockResolvedValue({ gender: [], nationality: [], marital_status: [] })
  api.post.mockResolvedValue({ id: 'p-1', full_name: 'Chan Tai Man' })
})

describe('AddPersonModal — discard guard (UAT F-1)', () => {
  it('closes straight away when nothing has been entered', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.click(container.querySelector('.overlay'))
    expect(onClose).toHaveBeenCalled()
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument()
  })

  it('asks before discarding a filled form dismissed by backdrop click', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(container.querySelector('.overlay'))
    expect(await screen.findByText('Discard changes?')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps the entered data when the operator chooses Keep editing', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(await screen.findByRole('button', { name: 'Keep editing' }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Full Name/)).toHaveValue('Chan Tai Man')
  })

  it('closes when the operator confirms Discard', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('AddPersonModal — required legend (UAT F-4)', () => {
  it('explains what the asterisk means', () => {
    renderModal()
    expect(screen.getByText(/Fields marked with an asterisk are required/)).toBeInTheDocument()
  })
})
