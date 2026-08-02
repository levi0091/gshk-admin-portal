import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CrCredentialsPage from './CrCredentialsPage.jsx'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('../lib/api.js', () => ({ api: { get: (...a) => get(...a), post: (...a) => post(...a), put: (...a) => put(...a) } }))

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const STORED = {
  presentor_account_id: 'T260727100116D',
  eservice_user_id: 'GSHKPN02',
  has_eservice_password: true,
  tpsi_password_hint: '•••••••4567',
  eservice_password_hint: '••••••••9021',
  tpsi_password_expires_at: '2027-01-23T00:00:00Z',
  deposit_account_no: 'ERG-2026-4521',
  is_test: true,
  last_rotated_at: '2026-08-02T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { hasPermission: () => true, isSuperAdmin: false }
  get.mockResolvedValue(STORED)
  put.mockResolvedValue(STORED)
  post.mockResolvedValue(STORED)
})

const renderPage = async () => {
  render(<CrCredentialsPage />)
  await screen.findByText('CR Credentials')
}

describe('CrCredentialsPage', () => {
  it('shows the stored password as a hint, not as a readable secret', async () => {
    await renderPage()
    const field = await screen.findByLabelText('TPSI login password')
    expect(field).toHaveValue('•••••••4567')
    // The last four are the point of the hint, so it must not be re-masked.
    expect(field).toHaveAttribute('type', 'text')
  })

  it('marks a password that is stored and one that is not', async () => {
    get.mockResolvedValue({ ...STORED, eservice_password_hint: null, has_eservice_password: false })
    await renderPage()
    expect(await screen.findByTestId('cr-tpsi-password-state')).toHaveTextContent('Stored')
    expect(screen.getByTestId('cr-eservice-password-state')).toHaveTextContent('Not set')
  })

  it('clears the field on focus so the hint is never submitted as a password', async () => {
    const user = userEvent.setup()
    await renderPage()
    const field = await screen.findByLabelText('TPSI login password')
    await user.click(field)
    expect(field).toHaveValue('')
    expect(field).toHaveAttribute('type', 'password')
  })

  it('restores the hint when focus leaves without anything typed', async () => {
    const user = userEvent.setup()
    await renderPage()
    const field = await screen.findByLabelText('TPSI login password')
    await user.click(field)
    await user.tab()
    await waitFor(() => expect(field).toHaveValue('•••••••4567'))
  })

  // ── The load-bearing behaviour ──────────────────────────────────────────
  // The backend reads a present-but-null field as "clear this column", so
  // sending null for untouched fields wipes stored secrets. CR forces a TPSI
  // password change every 180 days, which makes this the ROUTINE path.

  it('omits untouched passwords entirely when saving', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: /update credentials/i }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls[0][1]
    expect(body).not.toHaveProperty('tpsi_password')
    expect(body).not.toHaveProperty('eservice_password')
    expect(body.presentor_account_id).toBe('T260727100116D')
  })

  it('never sends the mask back as if it were a password', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: /update credentials/i }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(JSON.stringify(put.mock.calls[0][1])).not.toContain('•')
  })

  it('sends a password that was actually typed', async () => {
    const user = userEvent.setup()
    await renderPage()
    const field = await screen.findByLabelText('TPSI login password')
    await user.click(field)
    await user.type(field, 'BrandNewPw1')
    await user.click(screen.getByRole('button', { name: /update credentials/i }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].tpsi_password).toBe('BrandNewPw1')
  })

  it('can change the deposit account without re-supplying any password', async () => {
    const user = userEvent.setup()
    await renderPage()
    const deposit = screen.getByLabelText('Deposit account number')
    await user.clear(deposit)
    await user.type(deposit, 'N00108070000')
    await user.click(screen.getByRole('button', { name: /update credentials/i }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls[0][1]
    expect(body.deposit_account_no).toBe('N00108070000')
    expect(body).not.toHaveProperty('tpsi_password')
  })

  it('clears the signing password explicitly with null, not by omission', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: /clear signing password/i }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].eservice_password).toBeNull()
  })

  // ── First-time setup ────────────────────────────────────────────────────

  it('uses POST and demands a password when nothing is stored yet', async () => {
    const user = userEvent.setup()
    get.mockResolvedValue({})
    await renderPage()

    await user.type(screen.getByLabelText('Presenter account ID'), 'T999')
    await user.click(screen.getByRole('button', { name: /save credentials/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/TPSI login password is required/i)
    expect(post).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('TPSI login password'), 'FirstPw123')
    await user.click(screen.getByRole('button', { name: /save credentials/i }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1].tpsi_password).toBe('FirstPw123')
  })

  // ── Environment and expiry ──────────────────────────────────────────────

  it('says which CR environment the credential belongs to', async () => {
    await renderPage()
    // The backend refuses a credential whose is_test disagrees with TPSI_ENV,
    // and that refusal is otherwise an unexplained 502.
    expect(screen.getByText(/Connected to the CR TEST environment/i)).toBeInTheDocument()
  })

  it('warns when the TPSI password is close to expiring', async () => {
    const soon = new Date(Date.now() + 5 * 86400000).toISOString()
    get.mockResolvedValue({ ...STORED, tpsi_password_expires_at: soon })
    await renderPage()
    expect(await screen.findByText(/expires in 5 days/i)).toBeInTheDocument()
  })

  it('hides the save controls from a user who cannot write', async () => {
    auth = { hasPermission: (m, p) => m === 'tpsi' && p === 'read', isSuperAdmin: false }
    await renderPage()
    expect(screen.queryByRole('button', { name: /update credentials/i })).not.toBeInTheDocument()
  })

  it('surfaces a backend failure instead of silently doing nothing', async () => {
    const user = userEvent.setup()
    put.mockRejectedValue(new Error('credential is_test=true but TPSI_ENV=prod'))
    await renderPage()
    await user.click(screen.getByRole('button', { name: /update credentials/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/TPSI_ENV=prod/)
  })
})
