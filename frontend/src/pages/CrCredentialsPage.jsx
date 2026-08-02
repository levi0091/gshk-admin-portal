import { useState, useEffect, useCallback } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../context/AuthContext.jsx'

/**
 * Settings -> CR Credentials (wireframe_v10 s21).
 *
 * The logged-in user's own Companies Registry filing identity. Every filing they
 * make is presented under these credentials, and the NAR1 fee is drawn from the
 * deposit account named here.
 *
 * Two things about this screen are easy to get wrong:
 *
 *   1. OMITTING a password preserves it; sending null CLEARS it. The backend
 *      distinguishes the two (credentials._payload's _UNSET sentinel), and a
 *      routine TPSI password rotation must not wipe the stored signing password.
 *      So an untouched field is left OUT of the payload entirely -- see
 *      buildPayload.
 *   2. A stored password is echoed back masked except its last four characters.
 *      That hint is display-only: it is never sent back as if it were a new
 *      password, which would store literal bullet characters.
 */

/** A secret field that shows its stored hint until you focus it. */
function SecretField({ id, label, hint, value, onChange, help }) {
  const stored = Boolean(hint)
  // `value === null` means "untouched" -- show the hint, send nothing.
  const untouched = value === null
  const [focused, setFocused] = useState(false)

  return (
    <div className="f-group">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <label className="f-label" htmlFor={id} style={{ margin: 0 }}>{label}</label>
        <span
          className="role-tag"
          data-testid={`${id}-state`}
          style={
            stored
              ? { color: 'var(--bang)', background: 'var(--bang-10)' }
              : { color: 'var(--t-muted)', background: 'var(--indigo-10)' }
          }
        >
          {stored ? 'Stored' : 'Not set'}
        </span>
      </div>
      <input
        id={id}
        className="f-input"
        // Masked only while a real secret is being typed. The hint is already
        // masked, and rendering it as type=password would hide the last four
        // characters that make it recognisable.
        type={untouched ? 'text' : 'password'}
        value={untouched ? (hint || '') : value}
        placeholder={stored ? '' : 'Enter a password'}
        onFocus={() => { setFocused(true); if (untouched) onChange('') }}
        onBlur={() => { setFocused(false); if (value === '') onChange(null) }}
        onChange={(e) => onChange(e.target.value)}
        style={untouched ? { fontFamily: 'ui-monospace, Menlo, monospace', letterSpacing: '.06em' } : undefined}
      />
      <span className="f-hint">
        {help}
        {stored && !focused && ' Showing the last 4 characters of the stored password.'}
      </span>
    </div>
  )
}

function Meta({ label, children }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      gap: 12, padding: '10px 0', borderBottom: '1px solid var(--border)', fontSize: 12,
    }}>
      <span style={{ color: 'var(--t-muted)' }}>{label}</span>
      <span style={{ color: 'var(--t-head)', fontWeight: 700, textAlign: 'right' }}>{children}</span>
    </div>
  )
}

function daysUntil(iso) {
  if (!iso) return null
  const ms = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(ms)) return null
  return Math.ceil(ms / 86400000)
}

export default function CrCredentialsPage() {
  const { hasPermission, isSuperAdmin } = useAuth()
  const canWrite = isSuperAdmin || hasPermission('tpsi', 'write')

  const [meta, setMeta] = useState(undefined)   // undefined = loading
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [saving, setSaving] = useState(false)

  const [accountId, setAccountId] = useState('')
  const [depositAccount, setDepositAccount] = useState('')
  const [eserviceUserId, setEserviceUserId] = useState('')
  // null = untouched. '' = deliberately cleared. A string = a new secret.
  const [tpsiPassword, setTpsiPassword] = useState(null)
  const [eservicePassword, setEservicePassword] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await api.get('/tpsi/credentials')
      setMeta(data || {})
      setAccountId(data?.presentor_account_id || '')
      setDepositAccount(data?.deposit_account_no || '')
      setEserviceUserId(data?.eservice_user_id || '')
      setTpsiPassword(null)
      setEservicePassword(null)
    } catch (e) {
      setError(e.message)
      setMeta({})
    }
  }, [])

  useEffect(() => { load() }, [load])

  const isNew = meta && !meta.presentor_account_id

  /**
   * Untouched secrets are omitted, not sent as null.
   *
   * The backend reads a present-but-null field as "clear this column". Sending
   * null for every field the user did not touch would wipe the stored signing
   * password on the routine TPSI password rotation -- which CR forces every 180
   * days, so it is the common path, not an edge case.
   */
  function buildPayload() {
    const payload = {
      presentor_account_id: accountId.trim(),
      eservice_user_id: eserviceUserId.trim() || null,
      deposit_account_no: depositAccount.trim() || null,
    }
    if (tpsiPassword !== null) payload.tpsi_password = tpsiPassword
    if (eservicePassword !== null) payload.eservice_password = eservicePassword || null
    return payload
  }

  async function handleSave(e) {
    e.preventDefault()
    setError(null); setNotice(null)

    const payload = buildPayload()
    // tpsi_password is required by the API. On a rotation the stored one stands
    // in for an untouched field, but a first save has nothing to fall back on.
    if (isNew && !payload.tpsi_password) {
      setError('A TPSI login password is required to set up your credentials.')
      return
    }

    setSaving(true)
    try {
      // buildPayload already omits any password the user did not touch, and
      // PUT accepts a body with no tpsi_password at all (CredentialUpdateIn).
      const saved = isNew
        ? await api.post('/tpsi/credentials', payload)
        : await api.put('/tpsi/credentials', payload)
      setMeta(saved)
      setTpsiPassword(null)
      setEservicePassword(null)
      setNotice(isNew ? 'Credentials saved.' : 'Credentials updated.')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleClearSigningPassword() {
    setError(null); setNotice(null); setSaving(true)
    try {
      const saved = await api.put('/tpsi/credentials', {
        presentor_account_id: accountId.trim(),
        eservice_password: null,
      })
      setMeta(saved)
      setEservicePassword(null)
      setNotice('Stored signing password removed.')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (meta === undefined) {
    return <div className="empty-state" style={{ padding: 32 }}>Loading your CR credentials…</div>
  }

  const expiryDays = daysUntil(meta.tpsi_password_expires_at)
  const expirySoon = expiryDays !== null && expiryDays <= 30

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">CR Credentials</div>
          <div className="pg-sub">
            Your own Companies Registry filing identity. Every filing you make is
            presented under these credentials.
          </div>
        </div>
      </div>

      {error && (
        <div className="alert al-danger" role="alert" style={{ marginBottom: 16 }}>
          <span className="al-icon">⚠</span><div className="al-body">{error}</div>
        </div>
      )}
      {notice && (
        <div className="alert al-success" role="status" style={{ marginBottom: 16 }}>
          <span className="al-icon">✓</span><div className="al-body">{notice}</div>
        </div>
      )}

      {/* The backend refuses a credential whose is_test disagrees with TPSI_ENV,
          and that refusal is otherwise a baffling 502 — so say which it is. */}
      {meta.is_test !== undefined && (
        <div
          className="alert"
          style={{
            marginBottom: 16,
            background: meta.is_test ? 'var(--carrot-10)' : 'var(--bang-10)',
            borderColor: meta.is_test ? 'var(--carrot)' : 'var(--bang)',
          }}
        >
          <span className="al-icon">{meta.is_test ? '⚠' : '✓'}</span>
          <div className="al-body">
            <b>Connected to the CR {meta.is_test ? 'TEST' : 'PRODUCTION'} environment.</b>{' '}
            {meta.is_test
              ? 'These are test credentials and can only file against the CR test service. Production filing needs a separate set.'
              : 'Filings made with these credentials are real and chargeable.'}
          </div>
        </div>
      )}

      <div className="detail-grid client-off">
        <div>
          <form onSubmit={handleSave}>
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Presenter identity</div>
                  <div className="card-sub">Who CR sees as the filer</div>
                </div>
              </div>

              <div className="f-group">
                <label className="f-label" htmlFor="cr-account">Presenter account ID</label>
                <input
                  id="cr-account" className="f-input" value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  disabled={!canWrite} required
                />
                <span className="f-hint">Your TPSI account with the Companies Registry.</span>
              </div>

              <SecretField
                id="cr-tpsi-password"
                label="TPSI login password"
                hint={meta.tpsi_password_hint}
                value={tpsiPassword}
                onChange={setTpsiPassword}
                help="Authenticates you to TPSI. It never signs anything."
              />

              <div className="f-group" style={{ marginBottom: 0 }}>
                <label className="f-label" htmlFor="cr-deposit">Deposit account number</label>
                <input
                  id="cr-deposit" className="f-input" value={depositAccount}
                  onChange={(e) => setDepositAccount(e.target.value)}
                  disabled={!canWrite}
                />
                <span className="f-hint">
                  The account every filing fee is drawn from. NAR1 costs HK$105 per filing.
                </span>
              </div>
            </div>

            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Signing identity</div>
                  <div className="card-sub">Used when you sign a form yourself</div>
                </div>
              </div>

              <div className="reveal-note" style={{ color: 'var(--indigo)', background: 'var(--indigo-10)', marginBottom: 14 }}>
                <b>Two passwords, two jobs.</b> The TPSI password above authenticates.
                The e-Service password below signs. CR treats them differently.
              </div>

              <div className="f-group">
                <label className="f-label" htmlFor="cr-eservice-id">e-Service (e-Reg) user ID</label>
                <input
                  id="cr-eservice-id" className="f-input" value={eserviceUserId}
                  onChange={(e) => setEserviceUserId(e.target.value)}
                  disabled={!canWrite}
                />
                <span className="f-hint">
                  Your individual e-Filing account. CR rejects a signature from a corporate account.
                </span>
              </div>

              <SecretField
                id="cr-eservice-password"
                label="e-Service signing password"
                hint={meta.eservice_password_hint}
                value={eservicePassword}
                onChange={setEservicePassword}
                help="Stored so you can sign as company secretary without re-typing it. A client director's password is never stored — they enter it at the moment of signing."
              />
            </div>

            {canWrite && (
              <div className="action-bar">
                <div className="ab-note">
                  Leave a password field untouched to keep what is already stored.
                </div>
                <div className="ab-actions">
                  {meta.has_eservice_password && (
                    <button
                      type="button" className="btn btn-outline"
                      onClick={handleClearSigningPassword} disabled={saving}
                    >
                      Clear signing password
                    </button>
                  )}
                  <button type="submit" className="btn btn-action" disabled={saving}>
                    {saving ? 'Saving…' : isNew ? 'Save credentials' : 'Update credentials'}
                  </button>
                </div>
              </div>
            )}
          </form>
        </div>

        <div>
          {expiryDays !== null && (
            <div
              className="card mb-16"
              style={expirySoon ? { borderColor: 'var(--carrot)', background: 'var(--carrot-10)' } : undefined}
            >
              <div className="card-title" style={expirySoon ? { color: 'var(--carrot)' } : undefined}>
                {expiryDays <= 0
                  ? 'TPSI password has expired'
                  : `TPSI password expires in ${expiryDays} day${expiryDays === 1 ? '' : 's'}`}
              </div>
              <div className="f-hint" style={{ marginTop: 6, lineHeight: 1.5 }}>
                CR forces a change every 180 days. Change it before it stops a filing
                mid-submission.
              </div>
            </div>
          )}

          <div className="card mb-16">
            <div className="card-hdr"><div><div className="card-title">Status</div></div></div>
            <Meta label="Environment">
              <span className="role-tag" style={{
                color: meta.is_test ? 'var(--carrot)' : 'var(--bang)',
                background: meta.is_test ? 'var(--carrot-10)' : 'var(--bang-10)',
              }}>
                {meta.is_test ? 'TEST' : 'PRODUCTION'}
              </span>
            </Meta>
            <Meta label="Signing password">
              {meta.has_eservice_password
                ? <span style={{ color: 'var(--bang)' }}>Stored</span>
                : <span className="td-muted">Not set</span>}
            </Meta>
            <Meta label="Password expires">
              {meta.tpsi_password_expires_at
                ? new Date(meta.tpsi_password_expires_at).toLocaleDateString()
                : <span className="td-muted">—</span>}
            </Meta>
            <Meta label="Last rotated">
              {meta.last_rotated_at
                ? new Date(meta.last_rotated_at).toLocaleDateString()
                : <span className="td-muted">Never</span>}
            </Meta>
          </div>

          <div className="reveal-note" style={{ lineHeight: 1.55 }}>
            Passwords are encrypted at rest. A stored password is shown{' '}
            <b>masked except its last 4 characters</b>, so you can
            tell which one is saved without it being readable. Only you see your own —
            never another user, never a Super Admin.
          </div>
        </div>
      </div>
    </>
  )
}
