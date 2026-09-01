import { useState } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../context/AuthContext.jsx'

/**
 * First sign-in — replace the password G-FlowDesk generated (spec §7).
 *
 * WHY THIS IS A WHOLE SCREEN AND NOT A BANNER. The account cannot do anything
 * else: `middleware/auth` refuses every route except `/auth/me` and this one
 * while `must_change_password` is set. A banner over a working-looking portal
 * would have the user click into a page and be met with a 409 they cannot
 * interpret. There is one thing to do here, so there is one thing on screen.
 *
 * The redirect in App.jsx is the COURTESY, not the enforcement. Somebody who
 * types a URL past it gets 409s from the API rather than a portal.
 */
export default function SetPasswordPage() {
  const { profile, refreshProfile, signOut } = useAuth()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // The backend's floor, stated here so the message arrives before the round
  // trip rather than after it.
  const MIN = 8
  const tooShort = password.length > 0 && password.length < MIN
  const mismatch = confirm.length > 0 && password !== confirm
  const ready = password.length >= MIN && password === confirm

  async function submit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.post('/users/me/password', { new_password: password })
      // Re-read the identity rather than assuming: the flag is cleared server
      // side, and the app's routing decides on what /auth/me says. Guessing
      // here would let a failed clear leave the user on a portal the API
      // still refuses.
      await refreshProfile()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', background: 'var(--bg-page)',
                  padding: 20 }}>
      <div className="card" style={{ width: '100%', maxWidth: 420 }}>
        <div className="card-hdr">
          <div>
            <div className="card-title">Choose your password</div>
            <div className="card-sub">
              {profile?.display_name ? `Welcome, ${profile.display_name}. ` : ''}
              You are signed in with the password we emailed you. Choose your
              own before you go any further — nothing else opens until you do.
            </div>
          </div>
        </div>

        <form onSubmit={submit}>
          <div className="f-group">
            <label className="f-label" htmlFor="new-password">
              New password <span className="f-req">*</span>
            </label>
            <input id="new-password" className="f-input" type="password"
                   autoComplete="new-password" autoFocus value={password}
                   disabled={busy}
                   onChange={e => setPassword(e.target.value)} />
            <span className="f-hint">
              {tooShort
                ? `At least ${MIN} characters.`
                : `At least ${MIN} characters. Use something you do not use elsewhere.`}
            </span>
          </div>

          <div className="f-group">
            <label className="f-label" htmlFor="confirm-password">
              Confirm password <span className="f-req">*</span>
            </label>
            <input id="confirm-password" className="f-input" type="password"
                   autoComplete="new-password" value={confirm} disabled={busy}
                   onChange={e => setConfirm(e.target.value)} />
            {mismatch && (
              <span className="f-hint" style={{ color: 'var(--carrot)' }}>
                The two passwords do not match.
              </span>
            )}
          </div>

          {error && (
            <div className="alert al-danger" role="alert"
                 style={{ marginTop: 12 }}>
              <span className="al-icon">⚠</span>
              <div className="al-body">{error}</div>
            </div>
          )}

          <div className="action-bar" style={{ marginTop: 8 }}>
            <div className="ab-note">
              <button type="button" className="btn btn-outline btn-sm"
                      onClick={signOut} disabled={busy}>
                Sign out
              </button>
            </div>
            <div className="ab-actions">
              <button type="submit" className="btn btn-action"
                      disabled={!ready || busy}>
                {busy ? 'Saving…' : 'Save and continue'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
