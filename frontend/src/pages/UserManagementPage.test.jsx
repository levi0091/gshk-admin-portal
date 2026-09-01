import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const get = vi.fn()
const post = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn() },
}))

import UserManagementPage from './UserManagementPage.jsx'

const ROLES = [{ id: 'role-cm', name: 'Case Manager' }]

beforeEach(() => {
  vi.clearAllMocks()
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
