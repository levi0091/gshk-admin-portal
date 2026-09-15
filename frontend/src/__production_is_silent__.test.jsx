import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AppShell from './components/AppShell.jsx'
import UserManagementPage from './pages/UserManagementPage.jsx'

/**
 * NOTHING TELLS A PRODUCTION USER THEY ARE ON A TEST DEPLOYMENT (Levi
 * 2026-09-07: "all around the dev environment there are warnings about 'This is
 * a dev environment...' — make sure that does not appear in PROD").
 *
 * Every one of those notices is true and necessary on DEV. Each is gated, and
 * each was gated correctly when this was written — so this file is not a fix,
 * it is the guard that keeps it that way. They are gathered here rather than
 * left one per screen because the risk is not that one of them regresses in
 * isolation: it is that a NEW one gets added, ungated, by someone who did not
 * know there was a rule. A single failing file named for the rule is what makes
 * that visible.
 *
 * THE OTHER HALF OF EACH TEST IS THE POSITIVE CASE, in the same `it`. A
 * production-only assertion passes just as well when the notice has been
 * deleted, or when the selector stopped matching — which would quietly retire
 * the DEV warning that stops somebody mailing a real client.
 *
 * WHAT THIS CANNOT COVER. `is_test_env` comes from `GET /auth/me`, which reads
 * `APP_ENV` on the backend (services/app_env.py). If a PROD service is deployed
 * with `APP_ENV` unset it reports non-production and these notices appear —
 * correctly, because the mail interlock really is armed. That is a deployment
 * fact, not a frontend one; `GET /health` reports it without a token.
 */

let auth
vi.mock('./context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const get = vi.fn()
const post = vi.fn()
vi.mock('./lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a),
    patch: vi.fn(), del: vi.fn(), put: vi.fn(),
  },
}))

const PRODUCTION = { profile: { display_name: 'Levi', role_name: 'super_admin',
                                is_test_env: false, permissions: [] },
                     isSuperAdmin: true, hasPermission: () => true,
                     profileLoading: false, isTestEnv: false,
                     envUnknown: false }

const TEST_DEPLOYMENT = { ...PRODUCTION, isTestEnv: true }

beforeEach(() => {
  vi.clearAllMocks()
  auth = PRODUCTION
})

// ---------------------------------------------------------------------------

describe('the header badge', () => {
  const renderShell = () => render(
    <MemoryRouter initialEntries={['/x']}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="x" element={<div>page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )

  it('shows TEST off production and nothing on it', () => {
    auth = TEST_DEPLOYMENT
    const { unmount } = renderShell()
    expect(screen.getByText('TEST')).toBeInTheDocument()
    unmount()

    auth = PRODUCTION
    renderShell()
    expect(screen.queryByText('TEST')).not.toBeInTheDocument()
  })

  it('shows no ENV? badge when the backend answered "production"', () => {
    // The third state is a MISSING `is_test_env`, not a false one. A backend
    // that answered clearly must not be marked as having failed to answer.
    auth = { ...PRODUCTION, envUnknown: true }
    const { unmount } = renderShell()
    expect(screen.getByText(/ENV/)).toBeInTheDocument()
    unmount()

    auth = PRODUCTION
    renderShell()
    expect(screen.queryByText(/ENV/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------

describe('user management', () => {
  const ROLES = [{ id: 'role-cm', name: 'case_manager', role_permissions: [] }]
  const USERS = [{ id: 'u9', display_name: 'Roy Tan', email: 'roy@x.com',
                   role_id: 'role-cm', role_name: 'case_manager',
                   is_active: true }]

  beforeEach(() => {
    get.mockImplementation(url => Promise.resolve(
      String(url).includes('roles') ? ROLES : USERS))
  })

  /** Create a user and return the mounted tree, so the caller can unmount it. */
  const createUser = async redirected => {
    post.mockResolvedValue({ id: 'u9', welcome_email_sent: true,
                             welcome_email_redirected: redirected })
    const user = userEvent.setup()
    const view = render(<MemoryRouter><UserManagementPage /></MemoryRouter>)
    await screen.findByText('Roy Tan')
    await user.click(screen.getByRole('button', { name: /Add User/ }))
    await user.type(screen.getByPlaceholderText(/Sarah Wong/), 'New Person')
    await user.type(document.querySelector('input[type="email"]'), 'new@x.com')
    await user.selectOptions(screen.getByRole('combobox'), 'role-cm')
    await user.click(screen.getByRole('button', { name: /Create User/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    return view
  }

  it('mentions the test mailboxes only when the mail was redirected', async () => {
    // `welcome_email_redirected` is set by the backend and is only ever true
    // outside production (services/email_service._apply_test_recipient_lock),
    // so this is the flag doing the gating rather than the screen guessing.
    const { unmount } = await createUser(true)
    expect(await screen.findByText(/test environment/i)).toBeInTheDocument()
    unmount()

    await createUser(false)
    expect(screen.queryByText(/test environment/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/test mailboxes/i)).not.toBeInTheDocument()
  })
})
