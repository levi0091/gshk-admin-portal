import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CrCredentialsPage, { paneFor } from './CrCredentialsPage.jsx'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a), put: (...a) => put(...a) },
}))

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

// GET /tpsi/credentials — the signed-in user's own row.
const MINE = {
  presentor_account_id: 'T260727100116D',
  eservice_user_id: 'GSHKPN02',
  has_eservice_password: true,
  eservice_password_hint: '••••••••9021',
  is_test: true,
  last_rotated_at: '2026-08-02T00:00:00Z',
}

// GET /tpsi/shared-credential — the firm's single filing identity.
const SHARED = {
  presentor_account_id: 'T260727100116D',
  deposit_account_no: 'ERG-2026-4521',
  tpsi_password_hint: '•••••••4567',
  tpsi_password_expires_at: '2027-01-23T00:00:00Z',
  is_test: true,
  last_rotated_at: '2026-08-02T00:00:00Z',
}

// One mock, two endpoints — the page fetches whichever pane is showing.
function routeGet({ mine = MINE, shared = SHARED } = {}) {
  get.mockImplementation(path =>
    path === '/tpsi/shared-credential' ? Promise.resolve(shared) : Promise.resolve(mine))
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { hasPermission: () => true, isSuperAdmin: false }
  routeGet()
  put.mockResolvedValue(MINE)
  post.mockResolvedValue(MINE)
})

const renderPage = async () => {
  render(<CrCredentialsPage />)
  await screen.findByText('CR Credentials')
}

// ---------------------------------------------------------------------------
// Who may see the shared account (W-6, OQ-C)
// ---------------------------------------------------------------------------

describe('paneFor — the admin-only rule itself', () => {
  // Tested directly because it is the security-relevant decision on this
  // screen. Asserting it only through the rendered page hid it: the initial
  // tab value and the render guard used to enforce it twice, so a mutation
  // removing either left every test green.
  it('never resolves to the shared pane for a non-admin, whatever the tab says', () => {
    expect(paneFor(false, 'shared')).toBe('mine')
    expect(paneFor(false, 'mine')).toBe('mine')
    expect(paneFor(false, undefined)).toBe('mine')
  })

  it('lets an admin reach either pane', () => {
    expect(paneFor(true, 'shared')).toBe('shared')
    expect(paneFor(true, 'mine')).toBe('mine')
  })
})

describe('CrCredentialsPage — the shared account is admin-only', () => {
  it('is ENTIRELY ABSENT for an ordinary user, not disabled', async () => {
    // PRD §4, revising v11's own cr-lock-note: absent, not read-only. A control
    // you may never use is clutter, and a greyed-out field invites a support
    // ticket asking why it is greyed out.
    await renderPage()
    expect(screen.queryByRole('tab', { name: /shared/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Presenter account ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Deposit account number')).not.toBeInTheDocument()
  })

  it('never even asks the server for the shared account as an ordinary user', async () => {
    // Absent means not fetched. The endpoint is super-admin gated and would
    // answer 403, painting an error banner over a page that is working fine.
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    expect(get.mock.calls.some(c => c[0] === '/tpsi/shared-credential')).toBe(false)
  })

  it('lands an ordinary user straight on their own signing credentials', async () => {
    await renderPage()
    expect(await screen.findByLabelText('e-Service (e-Reg) user ID')).toBeInTheDocument()
    expect(screen.getByText(/Yours alone/)).toBeInTheDocument()
  })

  it('gives a Super Admin both tabs, opening on the shared account', async () => {
    auth = { hasPermission: () => true, isSuperAdmin: true }
    await renderPage()
    expect(screen.getByRole('tab', { name: /shared/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /My e-Service signing/i })).toBeInTheDocument()
    expect(await screen.findByLabelText('Presenter account ID')).toBeInTheDocument()
  })

  it('switches a Super Admin to their own pane and back', async () => {
    const user = userEvent.setup()
    auth = { hasPermission: () => true, isSuperAdmin: true }
    await renderPage()
    await screen.findByLabelText('Presenter account ID')

    await user.click(screen.getByRole('tab', { name: /My e-Service signing/i }))
    expect(await screen.findByLabelText('e-Service (e-Reg) user ID')).toBeInTheDocument()
    expect(screen.queryByLabelText('Presenter account ID')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /shared/i }))
    expect(await screen.findByLabelText('Presenter account ID')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The shared pane
// ---------------------------------------------------------------------------

describe('CrCredentialsPage — shared pane', () => {
  beforeEach(() => { auth = { hasPermission: () => true, isSuperAdmin: true } })

  it('reads the shared endpoint, not the per-user one', async () => {
    await renderPage()
    await screen.findByLabelText('Presenter account ID')
    expect(get.mock.calls.some(c => c[0] === '/tpsi/shared-credential')).toBe(true)
  })

  it('shows the stored password as a hint, not as a readable secret', async () => {
    await renderPage()
    const field = await screen.findByLabelText('TPSI login password')
    expect(field).toHaveValue('•••••••4567')
    // The last four are the point of the hint, so it must not be re-masked.
    expect(field).toHaveAttribute('type', 'text')
  })

  it('says plainly that the account is the firm\'s, not the user\'s', async () => {
    await renderPage()
    expect(await screen.findByText(/One presenter identity for the whole of GSHK/))
      .toBeInTheDocument()
  })

  it('refuses to save without a password rather than sending an empty one', async () => {
    // PUT /tpsi/shared-credential requires tpsi_password on EVERY save
    // (SharedCredentialIn.tpsi_password is a plain str). Sending '' would lock
    // GSHK's only CR account against an API that locks on failed auth.
    const user = userEvent.setup()
    await renderPage()
    await screen.findByLabelText('Presenter account ID')
    await user.click(screen.getByRole('button', { name: /Update shared account/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/requires it on every change/)
    expect(put).not.toHaveBeenCalled()
  })

  it('PUTs the account, password and deposit account together', async () => {
    const user = userEvent.setup()
    put.mockResolvedValue(SHARED)
    await renderPage()
    const pw = await screen.findByLabelText('TPSI login password')
    await user.click(pw)
    await user.type(pw, 'NewPass123')
    await user.click(screen.getByRole('button', { name: /Update shared account/ }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    const [path, body] = put.mock.calls[0]
    expect(path).toBe('/tpsi/shared-credential')
    expect(body.presentor_account_id).toBe('T260727100116D')
    expect(body.tpsi_password).toBe('NewPass123')
    expect(body.deposit_account_no).toBe('ERG-2026-4521')
  })

  it('marks an update to an existing account as a rotation', async () => {
    // rotated=true restarts the 180-day clock and clears the recorded expiry;
    // the old date would otherwise keep warning about a password that is gone.
    const user = userEvent.setup()
    put.mockResolvedValue(SHARED)
    await renderPage()
    const pw = await screen.findByLabelText('TPSI login password')
    await user.click(pw)
    await user.type(pw, 'NewPass123')
    await user.click(screen.getByRole('button', { name: /Update shared account/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].rotated).toBe(true)
  })

  it('does not mark a FIRST save as a rotation', async () => {
    const user = userEvent.setup()
    routeGet({ shared: {} })
    put.mockResolvedValue(SHARED)
    await renderPage()
    const account = await screen.findByLabelText('Presenter account ID')
    await user.type(account, 'T999')
    const pw = screen.getByLabelText('TPSI login password')
    await user.click(pw)
    await user.type(pw, 'FirstPass')
    await user.click(screen.getByRole('button', { name: /Save shared account/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].rotated).toBe(false)
  })

  it('warns which CR environment the credential belongs to', async () => {
    await renderPage()
    expect(await screen.findByText(/Connected to the CR TEST environment/))
      .toBeInTheDocument()
  })

  it('surfaces a server refusal instead of reporting success', async () => {
    const user = userEvent.setup()
    put.mockRejectedValue(new Error('is_test disagrees with TPSI_ENV'))
    await renderPage()
    const pw = await screen.findByLabelText('TPSI login password')
    await user.click(pw)
    await user.type(pw, 'x')
    await user.click(screen.getByRole('button', { name: /Update shared account/ }))
    expect(await screen.findByRole('alert'))
      .toHaveTextContent(/is_test disagrees with TPSI_ENV/)
  })
})

// ---------------------------------------------------------------------------
// The per-user pane
// ---------------------------------------------------------------------------

describe('CrCredentialsPage — my e-Service signing', () => {
  it('no longer offers the deposit account, which the shared record owns', async () => {
    // Since BE-5 `_deposit_account()` reads the shared record. Leaving the field
    // here would let a user edit a number that changes nothing about what is
    // charged — the worst kind of control.
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    expect(screen.queryByLabelText('Deposit account number')).not.toBeInTheDocument()
  })

  it('PUTs even on a first save, because POST demands a password that no longer exists', async () => {
    // CredentialIn.tpsi_password is a required non-nullable str, and since BE-5
    // there is no per-user TPSI password to supply. PUT upserts identically.
    const user = userEvent.setup()
    routeGet({ mine: {} })
    await renderPage()
    const id = await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.type(id, 'GSHKPN09')
    await user.click(screen.getByRole('button', { name: /Save credentials/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(post).not.toHaveBeenCalled()
    expect(put.mock.calls[0][0]).toBe('/tpsi/credentials')
  })

  it('never sends an empty presenter account id for the required field', async () => {
    const user = userEvent.setup()
    routeGet({ mine: {} })
    await renderPage()
    const id = await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.type(id, 'GSHKPN09')
    await user.click(screen.getByRole('button', { name: /Save credentials/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    // Falls back to the e-Service ID, which IS the CR identity that signs.
    expect(put.mock.calls[0][1].presentor_account_id).toBe('GSHKPN09')
  })

  it('refuses to save with nothing identifying the signer', async () => {
    const user = userEvent.setup()
    routeGet({ mine: {} })
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.click(screen.getByRole('button', { name: /Save credentials/ }))
    expect(await screen.findByRole('alert'))
      .toHaveTextContent(/Enter your e-Service user ID/)
    expect(put).not.toHaveBeenCalled()
  })

  it('omits an untouched password rather than sending null', async () => {
    // The backend reads a present-but-null field as "clear this column".
    const user = userEvent.setup()
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.click(screen.getByRole('button', { name: /Update credentials/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect('eservice_password' in put.mock.calls[0][1]).toBe(false)
  })

  it('sends a password that was actually typed', async () => {
    const user = userEvent.setup()
    await renderPage()
    const field = await screen.findByLabelText('e-Service signing password')
    await user.click(field)
    await user.type(field, 'Secret99')
    await user.click(screen.getByRole('button', { name: /Update credentials/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].eservice_password).toBe('Secret99')
  })

  it('never sends the masked hint back as if it were a new password', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.click(screen.getByRole('button', { name: /Update credentials/ }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(JSON.stringify(put.mock.calls[0][1])).not.toContain('•')
  })

  it('clears a stored signing password explicitly', async () => {
    const user = userEvent.setup()
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    await user.click(screen.getByRole('button', { name: 'Clear signing password' }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1].eservice_password).toBeNull()
  })

  it('hides the write controls from a read-only user', async () => {
    auth = { hasPermission: () => false, isSuperAdmin: false }
    await renderPage()
    await screen.findByLabelText('e-Service (e-Reg) user ID')
    expect(screen.queryByRole('button', { name: /Update credentials/ })).not.toBeInTheDocument()
  })

  it('states that the credential is personal and never shared', async () => {
    await renderPage()
    expect(await screen.findByText(/Yours alone/)).toBeInTheDocument()
  })
})
