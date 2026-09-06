import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const publicGet = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { publicGet: (...a) => publicGet(...a) },
}))
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ signIn: vi.fn() }),
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))

import LoginPage, { joinContacts } from './LoginPage.jsx'

beforeEach(() => {
  vi.clearAllMocks()
  publicGet.mockResolvedValue({ super_admins: [
    { display_name: 'Brian Yiu', email: 'brian@getstarted.hk' },
    { display_name: 'Vanis', email: 'vanis@getstarted.hk' },
  ] })
})

/**
 * Both notices used to name `levi@zenexflow.com` — the delivery contractor,
 * not GSHK's administrators. A locked-out GSHK user wrote to the wrong company,
 * and promoting somebody to super_admin changed nothing on the screen.
 */
describe('joinContacts', () => {
  it('reads as a sentence, not as an array', () => {
    expect(joinContacts([{ email: 'a@x.com' }])).toBe('a@x.com')
    expect(joinContacts([{ email: 'a@x.com' }, { email: 'b@x.com' }]))
      .toBe('a@x.com or b@x.com')
    expect(joinContacts(
      [{ email: 'a@x.com' }, { email: 'b@x.com' }, { email: 'c@x.com' }]))
      .toBe('a@x.com, b@x.com or c@x.com')
  })

  it('names NOBODY rather than somebody wrong', () => {
    // An address that is wrong is worse than no address: the reader stops
    // looking once they have one.
    expect(joinContacts([])).toBe('a Super Admin')
    expect(joinContacts(undefined)).toBe('a Super Admin')
    expect(joinContacts([{ display_name: 'No Mailbox' }])).toBe('a Super Admin')
  })
})

describe('LoginPage — who to contact', () => {
  it('names the actual super admins on Forgot password', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    await user.click(screen.getByText(/Forgot password/i))

    expect(await screen.findByText(
      /contact brian@getstarted\.hk or vanis@getstarted\.hk/i)).toBeInTheDocument()
  })

  it('names them on Request access too', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    await user.click(screen.getByText(/Request access/i))

    expect(await screen.findByText(
      /contact brian@getstarted\.hk or vanis@getstarted\.hk to request access/i))
      .toBeInTheDocument()
  })

  it('no longer hardcodes the delivery contractor', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    await user.click(screen.getByText(/Forgot password/i))

    expect(screen.queryByText(/levi@zenexflow\.com/)).not.toBeInTheDocument()
  })

  it('asks the API once, on mount — not when the link is pressed', async () => {
    // The notice has to appear the instant somebody clicks. A request fired at
    // that moment would show them the fallback for as long as the round trip
    // takes.
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    expect(publicGet).toHaveBeenCalledTimes(1)
    expect(publicGet).toHaveBeenCalledWith('/auth/super-admins')
  })

  it('sends no token — this screen has no session to send', async () => {
    // `api.get` THROWS when there is no session. Reaching for it here would
    // break the one screen that runs before sign-in.
    render(<LoginPage />)
    await screen.findByRole('button', { name: /Sign In/i })
    expect(publicGet.mock.calls[0]).toHaveLength(1)
  })

  it('still renders, and still says something useful, when the list fails', async () => {
    publicGet.mockRejectedValue(new Error('backend is down'))
    const user = userEvent.setup()
    render(<LoginPage />)
    await user.click(await screen.findByText(/Forgot password/i))

    expect(await screen.findByText(/contact a Super Admin/i)).toBeInTheDocument()
    // And the failure is not turned into an error the reader has to interpret.
    expect(screen.queryByText(/backend is down/)).not.toBeInTheDocument()
  })

  it('fills in the names when the list arrives AFTER the link was pressed', async () => {
    // The list is a round trip behind the screen. A reader who pressed the
    // link inside that window used to be left holding the fallback wording for
    // as long as they looked at it — which is why the state holds WHICH notice
    // is showing, not the finished sentence.
    let resolve
    publicGet.mockReturnValue(new Promise(r => { resolve = r }))
    const user = userEvent.setup()
    render(<LoginPage />)
    await user.click(screen.getByText(/Forgot password/i))
    expect(screen.getByText(/contact a Super Admin/i)).toBeInTheDocument()

    resolve({ super_admins: [{ email: 'brian@getstarted.hk' }] })
    expect(await screen.findByText(/contact brian@getstarted\.hk/i))
      .toBeInTheDocument()
  })

  it('shows the sign-in form regardless', async () => {
    publicGet.mockRejectedValue(new Error('backend is down'))
    render(<LoginPage />)
    expect(await screen.findByRole('button', { name: /Sign In/i }))
      .toBeInTheDocument()
  })
})
