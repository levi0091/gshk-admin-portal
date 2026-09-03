/**
 * NOT a test — a visual harness for the password-reset dialog and the login
 * screen's contact notice.
 *
 * Renders each with the real components and dumps the markup so it can be
 * screenshotted against the real stylesheet (see scripts/shoot-stages.mjs).
 * Reading JSX tells you what you wrote; a picture tells you what an
 * administrator sees a second before they take away somebody's password.
 *
 * The dialog is rendered inline rather than portalled, but it is `position:
 * fixed` over the whole viewport, so these shots dump `body` — the row behind
 * it is part of what is being judged.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/pages/__users_visual__.test.jsx
 *   node scripts/shoot-stages.mjs
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, vi, beforeEach, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const get = vi.fn()
const post = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn(),
    publicGet: (...a) => get(...a),
  },
}))
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ signIn: vi.fn(), profile: { id: 'u-levi' } }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))

import UserManagementPage from './UserManagementPage.jsx'
import LoginPage from './LoginPage.jsx'

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const ROLES = [
  { id: 'role-sa', name: 'super_admin' },
  { id: 'role-cm', name: 'case_manager' },
]

const USERS = [
  { id: 'u-roy', display_name: 'Roy Tan', email: 'roy@zenexflow.com',
    is_active: true, role_id: 'role-cm', roles: { name: 'case_manager' } },
  { id: 'u-brian', display_name: 'Brian Yiu', email: 'brian@getstarted.hk',
    is_active: true, role_id: 'role-sa', roles: { name: 'super_admin' } },
  { id: 'u-levi', display_name: 'Levi Z.', email: 'levi@zenexflow.com',
    is_active: true, role_id: 'role-sa', roles: { name: 'super_admin' } },
  { id: 'u-harry', display_name: 'Harry Lo', email: 'harry@getstarted.hk',
    is_active: false, role_id: 'role-sa', roles: { name: 'super_admin' } },
]

beforeEach(() => {
  vi.clearAllMocks()
  get.mockImplementation(url => Promise.resolve(
    String(url).includes('roles') ? ROLES
      : String(url).includes('super-admins')
        ? { super_admins: [
          { display_name: 'Brian Yiu', email: 'brian@getstarted.hk' },
          { display_name: 'Vanis', email: 'vanis@getstarted.hk' },
        ] }
        : USERS))
})

function write(name) {
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), document.body.innerHTML, 'utf8')
}

/** Open the reset dialog on one row, optionally pressing through it. */
async function dumpReset(name, { row = 'Roy Tan', confirm = null } = {}) {
  const user = userEvent.setup()
  render(<UserManagementPage />)
  await screen.findByText(row)
  const tr = screen.getByText(row).closest('tr')
  await user.click(within(tr).getByRole('button', { name: /Reset password/i }))

  if (confirm) {
    post.mockResolvedValue(confirm)
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
  }
  write(name)
}

describe.runIf(SHOOT)('user management visual harness', () => {
  it('reset · the confirmation', async () => {
    await dumpReset('u1-reset-confirm')
  })

  it('reset · confirming your own account', async () => {
    await dumpReset('u2-reset-self', { row: 'Levi Z.' })
  })

  it('reset · done, the mail is away', async () => {
    await dumpReset('u3-reset-sent', { confirm: {
      user_id: 'u-roy', email: 'roy@zenexflow.com',
      must_change_password: true, reset_email_sent: true,
      reset_email_redirected: false } })
  })

  it('reset · the mail did not send', async () => {
    await dumpReset('u4-reset-failed', { confirm: {
      user_id: 'u-roy', email: 'roy@zenexflow.com',
      must_change_password: true, reset_email_sent: false,
      reset_email_error: 'RESEND_API_KEY is not set' } })
  })

  it('reset · a test deployment redirected it', async () => {
    await dumpReset('u5-reset-redirected', { confirm: {
      user_id: 'u-roy', email: 'roy@zenexflow.com',
      must_change_password: true, reset_email_sent: true,
      reset_email_redirected: true } })
  })

  it('login · who to contact about a password', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    await user.click(screen.getByText(/Forgot password/i))
    await screen.findByText(/brian@getstarted\.hk/)
    write('u6-login-reset-notice')
  })

  it('login · who to contact about an account', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    await user.click(screen.getByText(/Request access/i))
    await screen.findByText(/to request access/)
    write('u7-login-access-notice')
  })
})
