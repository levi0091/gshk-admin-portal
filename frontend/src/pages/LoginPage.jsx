import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../lib/api.js'

// Self-service reset and access requests are not built (out of PBI-39 scope).
// The wireframe shows both links, so they are present and say what to do rather
// than being dead controls.
//
// THEY NAME THE PORTAL'S ACTUAL SUPER ADMINS, read from `/auth/super-admins`.
// Both strings used to name `levi@zenexflow.com` — the delivery contractor,
// not GSHK's administrators — so a locked-out GSHK user wrote to the wrong
// company, and promoting somebody to super_admin changed nothing on the screen.
//
// The fallback below is what shows when that list cannot be reached. It names
// nobody on purpose: an address that is wrong is worse than no address, because
// the reader stops looking once they have one.
const FALLBACK_CONTACT = 'a Super Admin'
const RESET_NOTICE = contacts =>
  `Password resets are handled by a Super Admin — contact ${contacts}.`
const ACCESS_NOTICE = contacts =>
  `Accounts are created by a Super Admin — contact ${contacts} to request access.`

/**
 * "brian@getstarted.hk", "brian@… or vanis@…", "a@…, b@… or c@…".
 *
 * Addresses, not names: the reader's next action is to open a mail client, and
 * a name they then have to look up is a step this screen can spend for them.
 */
export function joinContacts(superAdmins) {
  const emails = (superAdmins || []).map(a => a?.email).filter(Boolean)
  if (emails.length === 0) return FALLBACK_CONTACT
  if (emails.length === 1) return emails[0]
  return `${emails.slice(0, -1).join(', ')} or ${emails[emails.length - 1]}`
}

export default function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  // WHICH notice is showing, not the sentence itself. The contact list arrives
  // a round trip after the screen does, and a reader who pressed the link in
  // that window would otherwise be left holding the fallback wording for as
  // long as they looked at it.
  const [noticeKey, setNoticeKey] = useState(null)
  const [loading, setLoading] = useState(false)
  const [contacts, setContacts] = useState(FALLBACK_CONTACT)
  const notice = noticeKey === 'reset' ? RESET_NOTICE(contacts)
    : noticeKey === 'access' ? ACCESS_NOTICE(contacts)
      : ''

  // Fetched on mount rather than when a link is pressed: the notice has to
  // appear the instant somebody clicks "Forgot password?", and a request fired
  // at that moment would show them the fallback for as long as the round trip
  // takes. A failure is silent — the fallback wording is already correct.
  useEffect(() => {
    let live = true
    api.publicGet('/auth/super-admins')
      .then(data => { if (live) setContacts(joinContacts(data?.super_admins)) })
      .catch(() => {})
    return () => { live = false }
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setNoticeKey(null)
    setLoading(true)
    try {
      await signIn(email, password)
      navigate('/')
    } catch (err) {
      setError(err.message || 'Sign in failed. Check credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--indigo-5)', padding: 24,
    }}>
      <div
        className="login-card-wrap"
        style={{
          background: '#fff', border: '1px solid var(--border)',
          borderRadius: 'var(--r-xl)', padding: '44px 40px',
          width: '100%', maxWidth: 410, boxShadow: 'var(--sh-lg)',
        }}
      >
        {/* Logo — full GSHK horizontal brand logo, text baked into image */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, marginBottom: 28 }}>
          <img
            src="/gshk-logo.png"
            style={{ maxWidth: 200, height: 'auto', display: 'block', marginBottom: 4 }}
            alt="GetStartedHK"
          />
        </div>

        <div style={{ height: 1, background: 'var(--border)', margin: '0 0 22px' }} />

        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--t-head)', textAlign: 'center', marginBottom: 4 }}>
          G-FlowDesk Admin Portal
        </div>
        <div style={{ fontSize: 12, color: 'var(--t-muted)', textAlign: 'center', marginBottom: 22 }}>
          Sign in to G-FlowDesk — company lifecycle management
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            {/* htmlFor/id, not a bare <label>: an unassociated label is not a
                label to a screen reader, and clicking it does not focus the
                field. autoComplete lets a password manager fill the form. */}
            <label htmlFor="login-email" style={{ fontSize: 11, fontWeight: 600, color: 'var(--t-head)', display: 'block', marginBottom: 5 }}>
              Email address
            </label>
            <input
              id="login-email"
              name="email"
              autoComplete="username"
              className="f-input"
              style={{ width: '100%', height: 42, fontSize: 14 }}
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="login-password" style={{ fontSize: 11, fontWeight: 600, color: 'var(--t-head)', display: 'block', marginBottom: 5 }}>
              Password
            </label>
            <input
              id="login-password"
              name="password"
              autoComplete="current-password"
              className="f-input"
              style={{ width: '100%', height: 42, fontSize: 14 }}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="forgot-row">
            <span className="forgot-link" onClick={() => setNoticeKey('reset')}>
              Forgot password?
            </span>
          </div>

          {error && (
            <div style={{
              background: '#FEE2E2', border: '1px solid #FCA5A5',
              borderRadius: 'var(--r-sm)', padding: '10px 14px',
              fontSize: 13, color: '#B91C1C',
            }}>
              {error}
            </div>
          )}

          {notice && (
            <div style={{
              background: 'var(--indigo-5)', border: '1px solid var(--border)',
              borderRadius: 'var(--r-sm)', padding: '10px 14px',
              fontSize: 12, color: 'var(--t-body)',
            }}>
              {notice}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%', height: 46, background: 'var(--indigo)', color: '#fff',
              borderRadius: 'var(--r)', fontSize: 14, fontWeight: 700,
              letterSpacing: '.03em', border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--font)', transition: '.15s', marginTop: 4,
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div className="login-footer">
          Don&apos;t have an account?{' '}
          <span className="login-lnk" onClick={() => setNoticeKey('access')}>
            Request access
          </span>
        </div>
      </div>
    </div>
  )
}
