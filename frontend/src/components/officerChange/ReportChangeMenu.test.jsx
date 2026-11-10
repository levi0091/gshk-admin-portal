import { render, screen, waitFor, renderHook, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ReportChangeMenu, { useStartOfficerChange } from './ReportChangeMenu.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})
const post = vi.fn()
vi.mock('../../lib/api.js', () => ({ api: { post: (...a) => post(...a) } }))

beforeEach(() => vi.clearAllMocks())

describe('ReportChangeMenu', () => {
  it('opens on demand and offers ND2A and ND2B', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><ReportChangeMenu entityId="e1" /></MemoryRouter>)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Report a change/ }))
    expect(screen.getByRole('menuitem', { name: /Appoint or cease an officer/ })).toHaveFocus()
    expect(screen.getByRole('menuitem', { name: /Change an officer's particulars/ })).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><ReportChangeMenu entityId="e1" /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: /Report a change/ }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('opens (or reuses) the ND2A and goes to it', async () => {
    post.mockResolvedValue({ case: { id: 'k1' }, reused: true })
    const user = userEvent.setup()
    render(<MemoryRouter><ReportChangeMenu entityId="e1" /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: /Report a change/ }))
    await user.click(screen.getByRole('menuitem', { name: /Appoint or cease/ }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/officer-changes/k1'))
    expect(post).toHaveBeenCalledWith('/officer-changes', { entity_id: 'e1', form_code: 'Nd2a' })
  })

  it('says why when the case cannot be opened', async () => {
    post.mockRejectedValue(new Error('This company has been deleted'))
    const user = userEvent.setup()
    render(<MemoryRouter><ReportChangeMenu entityId="e1" /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: /Report a change/ }))
    await user.click(screen.getByRole('menuitem', { name: /particulars/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This company has been deleted')
    expect(navigate).not.toHaveBeenCalled()
  })
})

describe('useStartOfficerChange', () => {
  const hook = () => renderHook(() => useStartOfficerChange('e1'),
    { wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter> })

  it('lands a Cease on the case with the officer to open the drawer on', async () => {
    post.mockResolvedValue({ case: { id: 'k1' } })
    const { result } = hook()
    await act(() => result.current.start('Nd2a', { cease: 'cs:S1' }))
    expect(navigate).toHaveBeenCalledWith('/officer-changes/k1?cease=cs%3AS1')
  })

  it('adds a Change particulars entry, and an officer already on the case is not an error', async () => {
    post.mockResolvedValueOnce({ case: { id: 'k2' } })
      .mockRejectedValueOnce(new Error('That officer is already on this form'))
    const { result } = hook()
    await act(() => result.current.start('Nd2b', { entry: { kind: 'change', officer_id: 'o1' } }))
    expect(post).toHaveBeenLastCalledWith('/officer-changes/k2/entries', { kind: 'change', officer_id: 'o1' })
    expect(navigate).toHaveBeenCalledWith('/officer-changes/k2')
    expect(result.current.error).toBeNull()
  })

  it('stops on any other refusal of the entry', async () => {
    post.mockResolvedValueOnce({ case: { id: 'k2' } })
      .mockRejectedValueOnce(new Error('That is not a current officer of this company'))
    const { result } = hook()
    await act(() => result.current.start('Nd2b', { entry: { kind: 'change', officer_id: 'o9' } }))
    expect(navigate).not.toHaveBeenCalled()
    expect(result.current.error).toBe('That is not a current officer of this company')
  })
})
