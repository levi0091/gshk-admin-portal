import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const get = vi.fn()
const post = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn() },
}))

let auth = { profile: { id: 'admin-1' } }
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

import UserManagementPage from './UserManagementPage.jsx'

const ROLES = [{ id: 'role-cm', name: 'Case Manager' }]
const STAFF = {
  id: 'u9', display_name: 'Roy Tan', email: 'roy@x.com',
  is_active: true, role_id: 'role-cm', roles: { name: 'Case Manager' },
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { profile: { id: 'admin-1' } }
  get.mockImplementation(url => Promise.resolve(
    String(url).includes('roles') ? ROLES : []))
  post.mockResolvedValue({ id: 'u9', display_name: 'Roy',
                           welcome_email_sent: true })
})

async function openAddUser() {
  const user = userEvent.setup()
  render(<UserManagementPage />)
  await user.click(await screen.findByRole('button', { name: /Add User/i }))
  return user
}

/**
 * Spec §7 — an administrator no longer chooses a colleague's password.
 */
describe('UserManagementPage — adding a user', () => {
  it('has NO password field at all', async () => {
    // Removed, not disabled. A disabled box still tells the administrator that
    // choosing a password is a thing they normally do here.
    await openAddUser()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    const passwordInputs = document.querySelectorAll('input[type="password"]')
    expect(passwordInputs).toHaveLength(0)
  })

  it('says what happens instead, so the absence is not a mystery', async () => {
    await openAddUser()
    expect(screen.getByText(/emails them a password/i)).toBeInTheDocument()
    expect(screen.getByText(/Nobody else ever sees it/i)).toBeInTheDocument()
  })

  it('posts exactly three fields', async () => {
    const user = await openAddUser()
    await user.type(screen.getByPlaceholderText(/Sarah Wong/), 'Roy Tan')
    await user.type(document.querySelector('input[type="email"]'), 'roy@x.com')
    await user.selectOptions(screen.getByRole('combobox'), 'role-cm')
    await user.click(screen.getByRole('button', { name: /Create User/ }))

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toEqual({
      display_name: 'Roy Tan', email: 'roy@x.com', role_id: 'role-cm' })
  })

  it('warns — and stays open — when the welcome email did not send', async () => {
    // The account EXISTS. Closing the modal on a success message would leave a
    // real user who can never sign in and an administrator who thinks the job
    // is done.
    post.mockResolvedValue({ id: 'u9', welcome_email_sent: false,
                             welcome_email_error: 'RESEND_API_KEY is not set' })
    const user = await openAddUser()
    await user.type(screen.getByPlaceholderText(/Sarah Wong/), 'Roy Tan')
    await user.type(document.querySelector('input[type="email"]'), 'roy@x.com')
    await user.selectOptions(screen.getByRole('combobox'), 'role-cm')
    await user.click(screen.getByRole('button', { name: /Create User/ }))

    expect(await screen.findByText(/the welcome email did not send/i))
      .toBeInTheDocument()
    expect(screen.getByText(/RESEND_API_KEY is not set/)).toBeInTheDocument()
    // And it says what to do about it, rather than only what went wrong.
    expect(screen.getByText(/deactivate this account and create it again/i))
      .toBeInTheDocument()
  })

  it('closes on a clean create', async () => {
    const user = await openAddUser()
    await user.type(screen.getByPlaceholderText(/Sarah Wong/), 'Roy Tan')
    await user.type(document.querySelector('input[type="email"]'), 'roy@x.com')
    await user.selectOptions(screen.getByRole('combobox'), 'role-cm')
    await user.click(screen.getByRole('button', { name: /Create User/ }))

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Create User/ }))
        .not.toBeInTheDocument())
  })
})

describe('UserManagementPage — a test deployment', () => {
  it('says the password went to the test mailboxes, not to the new user', async () => {
    // The account is real and locked to `must_change_password`. Unless the new
    // user is one of the four TEST_RECIPIENTS they can never sign in, and
    // nothing else on this screen would say why.
    post.mockResolvedValue({ id: 'u9', welcome_email_sent: true,
                             welcome_email_redirected: true })
    const user = await openAddUser()
    await user.type(screen.getByPlaceholderText(/Sarah Wong/), 'Roy Tan')
    await user.type(document.querySelector('input[type="email"]'), 'roy@x.com')
    await user.selectOptions(screen.getByRole('combobox'), 'role-cm')
    await user.click(screen.getByRole('button', { name: /Create User/ }))

    expect(await screen.findByText(/test environment/i)).toBeInTheDocument()
    expect(screen.getByText(/roy@x\.com/)).toBeInTheDocument()
    expect(screen.getByText(/cannot sign in until somebody passes them/i))
      .toBeInTheDocument()
  })
})

/**
 * Resetting a colleague's password.
 *
 * The confirmation exists for ONE reason: two rows in this table can carry the
 * same display name, and an administrator who resets the wrong account has
 * locked a working colleague out with no undo. So the address — the identifier
 * that is actually unique — is what the dialog puts in front of them.
 */
describe('UserManagementPage — resetting a password', () => {
  const users = list => get.mockImplementation(url => Promise.resolve(
    String(url).includes('roles') ? ROLES : list))

  async function openReset(row = STAFF) {
    users([row])
    const user = userEvent.setup()
    render(<UserManagementPage />)
    await user.click(await screen.findByRole('button', { name: /Reset password/i }))
    return user
  }

  it('names the account by EMAIL, not only by display name', async () => {
    await openReset()
    expect(screen.getByText(/The new password will be emailed to/i))
      .toBeInTheDocument()
    // Inside the dialog, not merely somewhere in the table behind it.
    expect(within(screen.getByRole('button', { name: /^Reset Password$/ })
      .closest('.modal')).getByText('roy@x.com')).toBeInTheDocument()
  })

  it('says the current password stops working, before anything happens', async () => {
    await openReset()
    expect(screen.getByText(/current password stops working immediately/i))
      .toBeInTheDocument()
  })

  it('does NOT reset anything until the dialog is confirmed', async () => {
    await openReset()
    expect(post).not.toHaveBeenCalled()
  })

  it('cancelling resets nothing', async () => {
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /Cancel/ }))
    expect(post).not.toHaveBeenCalled()
    expect(screen.queryByText(/The new password will be emailed to/i))
      .not.toBeInTheDocument()
  })

  it('posts to the confirmed user and nobody else', async () => {
    post.mockResolvedValue({ user_id: 'u9', email: 'roy@x.com',
                             must_change_password: true,
                             reset_email_sent: true })
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][0]).toBe('/users/u9/reset-password')
  })

  it('confirms where the password went', async () => {
    post.mockResolvedValue({ user_id: 'u9', email: 'roy@x.com',
                             must_change_password: true,
                             reset_email_sent: true })
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    expect(await screen.findByText(/on its way to/i)).toBeInTheDocument()
  })

  it('offers no second press once the password has already changed', async () => {
    // Everything after the POST is the AFTER state: the old password is gone,
    // so there is nothing left to cancel and nothing to confirm again.
    post.mockResolvedValue({ user_id: 'u9', email: 'roy@x.com',
                             must_change_password: true,
                             reset_email_sent: true })
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    await waitFor(() => expect(
      screen.queryByRole('button', { name: /^Reset Password$/ }))
      .not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Close/ })).toBeInTheDocument()
  })

  it('says they are locked out when the email did not send', async () => {
    // Worse than the equivalent on creation: their old password has ALREADY
    // stopped working, so silence here is a colleague who cannot sign in.
    post.mockResolvedValue({ user_id: 'u9', email: 'roy@x.com',
                             must_change_password: true,
                             reset_email_sent: false,
                             reset_email_error: 'RESEND_API_KEY is not set' })
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    expect(await screen.findByText(/the email did not send/i)).toBeInTheDocument()
    expect(screen.getByText(/RESEND_API_KEY is not set/)).toBeInTheDocument()
    expect(screen.getByText(/locked out until this is delivered/i))
      .toBeInTheDocument()
  })

  it('says the password went to the test mailboxes on a test deployment', async () => {
    post.mockResolvedValue({ user_id: 'u9', email: 'roy@x.com',
                             must_change_password: true,
                             reset_email_sent: true,
                             reset_email_redirected: true })
    const user = await openReset()
    await user.click(screen.getByRole('button', { name: /^Reset Password$/ }))
    expect(await screen.findByText(/test environment/i)).toBeInTheDocument()
    expect(screen.getByText(/cannot sign in until somebody passes them/i))
      .toBeInTheDocument()
  })

  it('warns when the administrator is resetting their OWN account', async () => {
    auth = { profile: { id: 'u9' } }
    await openReset()
    expect(screen.getByText(/This is your own account/i)).toBeInTheDocument()
  })

  it('does not cry self on somebody else', async () => {
    await openReset()
    expect(screen.queryByText(/This is your own account/i)).not.toBeInTheDocument()
  })

  it('is offered for super admins too — a reset removes nobody access', async () => {
    await openReset({ ...STAFF, id: 'sa-2', display_name: 'Vanis',
                      email: 'vanis@getstarted.hk',
                      roles: { name: 'super_admin' } })
    // Scoped to the dialog: the address is also in the row behind it.
    expect(within(screen.getByRole('button', { name: /^Reset Password$/ })
      .closest('.modal')).getByText('vanis@getstarted.hk')).toBeInTheDocument()
  })

  it('is NOT offered for a deactivated account', async () => {
    // Banned in Auth. The backend refuses with a 409, and a button that always
    // fails is worse than no button.
    users([{ ...STAFF, is_active: false }])
    render(<UserManagementPage />)
    await screen.findByText('Roy Tan')
    expect(screen.queryByRole('button', { name: /Reset password/i }))
      .not.toBeInTheDocument()
  })
})
