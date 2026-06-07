import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
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
      background: 'var(--indigo-5)', padding: 24, minHeight: '100vh',
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
          Sign in to access the NAR1 case management system
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--t-head)', display: 'block', marginBottom: 5 }}>
              Email address
            </label>
            <input
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
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--t-head)', display: 'block', marginBottom: 5 }}>
              Password
            </label>
            <input
              className="f-input"
              style={{ width: '100%', height: 42, fontSize: 14 }}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
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

        <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--t-muted)', marginTop: 18 }}>
          Access restricted to authorised ZenexFlow administrators.
        </div>
      </div>
    </div>
  )
}
