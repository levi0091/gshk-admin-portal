import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const post = vi.fn()
vi.mock('../lib/api.js', () => ({ api: { post: (...a) => post(...a) } }))

const refreshProfile = vi.fn()
const signOut = vi.fn()
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

import SetPasswordPage from './SetPasswordPage.jsx'

beforeEach(() => {
  vi.clearAllMocks()
  post.mockResolvedValue({ must_change_password: false })
  auth = { profile: { display_name: 'Roy Tan' }, refreshProfile, signOut }
})

/**
 * Spec §7 — the screen a new user meets on their first sign-in.
 *
 * The enforcement lives in the API (`middleware/auth` refuses every route while
 * the flag is set). This screen's job is to make the one available action
 * obvious, and to not let the user send something the API will reject.
 */
describe('SetPasswordPage', () => {
  it('says why the user is here rather than showing a bare form', async () => {
    render(<SetPasswordPage />)
    expect(screen.getByText(/Choose your password/)).toBeInTheDocument()
    expect(screen.getByText(/nothing else opens until you do/)).toBeInTheDocument()
  })

  it('greets the user by name when the profile has one', () => {
    render(<SetPasswordPage />)
    expect(screen.getByText(/Welcome, Roy Tan/)).toBeInTheDocument()
  })

  it('does not greet a nameless profile with an empty space', () => {
    auth = { profile: null, refreshProfile, signOut }
    render(<SetPasswordPage />)
    expect(screen.queryByText(/Welcome,/)).not.toBeInTheDocument()
    expect(screen.getByText(/You are signed in with the password we emailed/))
      .toBeInTheDocument()
  })

  it('will not submit until the password is long enough', async () => {
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    await user.type(screen.getByLabelText(/New password/), 'short')
    await user.type(screen.getByLabelText(/Confirm password/), 'short')
    expect(screen.getByRole('button', { name: /Save and continue/ })).toBeDisabled()
  })

  it('will not submit until the two entries match', async () => {
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    await user.type(screen.getByLabelText(/New password/), 'a-decent-password')
    await user.type(screen.getByLabelText(/Confirm password/), 'a-different-one')
    expect(screen.getByRole('button', { name: /Save and continue/ })).toBeDisabled()
    expect(screen.getByText(/do not match/)).toBeInTheDocument()
  })

  it('sends the new password and then RE-READS the identity', async () => {
    // Guessing the flag is cleared would leave a user on a portal the API
    // still refuses. The routing decides on what /auth/me says.
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    await user.type(screen.getByLabelText(/New password/), 'a-decent-password')
    await user.type(screen.getByLabelText(/Confirm password/), 'a-decent-password')
    await user.click(screen.getByRole('button', { name: /Save and continue/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/users/me/password', { new_password: 'a-decent-password' }))
    await waitFor(() => expect(refreshProfile).toHaveBeenCalled())
  })

  it('shows the API refusal rather than swallowing it', async () => {
    post.mockRejectedValue(Object.assign(
      new Error('Password change failed: too common'), { status: 400 }))
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    await user.type(screen.getByLabelText(/New password/), 'a-decent-password')
    await user.type(screen.getByLabelText(/Confirm password/), 'a-decent-password')
    await user.click(screen.getByRole('button', { name: /Save and continue/ }))
    expect(await screen.findByText(/too common/)).toBeInTheDocument()
    // Still on the screen, still able to try again.
    expect(screen.getByLabelText(/New password/)).toBeEnabled()
  })

  it('offers a way out for someone who should not be here', async () => {
    // A user who received someone else's invitation must be able to leave
    // without a password change they have no business making.
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    await user.click(screen.getByRole('button', { name: /Sign out/ }))
    expect(signOut).toHaveBeenCalled()
  })

  it('does not put the password in the DOM as readable text', async () => {
    const user = userEvent.setup()
    render(<SetPasswordPage />)
    const field = screen.getByLabelText(/New password/)
    await user.type(field, 'a-decent-password')
    expect(field).toHaveAttribute('type', 'password')
  })
})
