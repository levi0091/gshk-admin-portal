import { useState, useEffect, useCallback } from 'react'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import { useAuth } from '../context/AuthContext.jsx'

/**
 * Settings -> CR Credentials (wireframe_v11 s21).
 *
 * TWO CREDENTIALS, TWO OWNERS. This is the whole point of the screen, and the
 * one thing a reader must not get wrong:
 *
 *   - The SHARED CR/TPSI account (BE-5, W-6) is GSHK's single filing identity.
 *     Every user files under it and every NAR1 fee is drawn from its deposit
 *     account. `routers/tpsi.client_for()` authenticates every CR call with it,
 *     and `_deposit_account()` reads the fee account from it. It belongs to the
 *     firm, so only a Super Admin may change it (OQ-C 2026-08-16) — holding
 *     `tpsi:write` lets you file under it, not repoint it at another CR account.
 *
 *   - The per-user e-SERVICE SIGNING credential stays personal. Signing is a
 *     personal act, and CR rejects a signature from a corporate account.
 *
 * For an ordinary user the shared account is ABSENT — no tab, no pane, not a
 * read-only rendering (PRD §4, revising v11's own `cr-lock-note`). A control
 * you may never use is clutter, and a greyed-out field invites a support
 * ticket asking why it is greyed out.
 *
 * Two things about the secret fields are easy to get wrong:
 *
 *   1. OMITTING a password preserves it; sending null CLEARS it. The backend
 *      distinguishes the two (credentials._payload's _UNSET sentinel), and a
 *      routine TPSI password rotation must not wipe the stored signing password.
 *      So an untouched field is left OUT of the payload entirely.
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

function EnvBanner({ isTest }) {
  if (isTest === undefined || isTest === null) return null
  // The backend refuses a credential whose is_test disagrees with TPSI_ENV,
  // and that refusal is otherwise a baffling 502 — so say which it is.
  return (
    <div
      className="alert"
      style={{
        marginBottom: 16,
        background: isTest ? 'var(--carrot-10)' : 'var(--bang-10)',
        borderColor: isTest ? 'var(--carrot)' : 'var(--bang)',
      }}
    >
      <span className="al-icon">{isTest ? '⚠' : '✓'}</span>
      <div className="al-body">
        <b>Connected to the CR {isTest ? 'TEST' : 'PRODUCTION'} environment.</b>{' '}
        {isTest
          ? 'These are test credentials and can only file against the CR test service. Production filing needs a separate set.'
          : 'Filings made with these credentials are real and chargeable.'}
      </div>
    </div>
  )
}

function ExpiryCard({ meta }) {
  const days = daysUntil(meta.tpsi_password_expires_at)
  if (days === null) return null
  const soon = days <= 30
  return (
    <div
      className="card mb-16"
      style={soon ? { borderColor: 'var(--carrot)', background: 'var(--carrot-10)' } : undefined}
    >
      <div className="card-title" style={soon ? { color: 'var(--carrot)' } : undefined}>
        {days <= 0
          ? 'TPSI password has expired'
          : `TPSI password expires in ${days} day${days === 1 ? '' : 's'}`}
      </div>
      <div className="f-hint" style={{ marginTop: 6, lineHeight: 1.5 }}>
        CR forces a change every 180 days. Change it before it stops a filing
        mid-submission.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// The shared GSHK presenter account — Super Admin only
// ---------------------------------------------------------------------------

function SharedPane({ onNotice, onError }) {
  const [meta, setMeta] = useState(undefined)
  const [saving, setSaving] = useState(false)
  const [accountId, setAccountId] = useState('')
  const [depositAccount, setDepositAccount] = useState('')
  const [password, setPassword] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await api.get('/tpsi/shared-credential')
      setMeta(data || {})
      setAccountId(data?.presentor_account_id || '')
      setDepositAccount(data?.deposit_account_no || '')
      setPassword(null)
    } catch (e) {
      onError(e.message)
      setMeta({})
    }
  }, [onError])

  useEffect(() => { load() }, [load])

  if (meta === undefined) {
    return <div className="empty-state" style={{ padding: 32 }}>Loading the shared CR account…</div>
  }

  const isNew = !meta.presentor_account_id

  async function handleSave(e) {
    e.preventDefault()
    onError(null); onNotice(null)

    // A password is needed only when there is nothing stored to fall back on.
    // On an edit it is OMITTED unless deliberately changed: the common edit is
    // the deposit account, and making that require the password to be retyped
    // from memory risks storing a typo — which surfaces only at CR, as a failed
    // authentication, against the one account the whole firm files through.
    if (isNew && !password) {
      onError('Enter the TPSI login password — nothing is stored yet for the '
            + 'shared CR account.')
      return
    }

    setSaving(true)
    try {
      const body = {
        presentor_account_id: accountId.trim(),
        deposit_account_no: depositAccount.trim() || null,
        // A rotation clears the recorded expiry: the 180-day clock restarts and
        // the old date would otherwise keep warning about a password that is
        // gone. Only a real password change is a rotation.
        rotated: Boolean(password) && !isNew,
      }
      if (password) body.tpsi_password = password
      const saved = await api.put('/tpsi/shared-credential', body)
      setMeta(saved)
      setPassword(null)
      onNotice(isNew ? 'Shared CR account saved.' : 'Shared CR account updated.')
    } catch (e) {
      onError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <EnvBanner isTest={meta.is_test} />

      <div className="cr-scope shared">
        <div>
          <b>One presenter identity for the whole of GSHK.</b> Every G-FlowDesk
          user files under this account, and every NAR1 fee is drawn from its
          deposit account. It is not yours — it is the firm's.
        </div>
      </div>

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
                <label className="f-label" htmlFor="shared-account">Presenter account ID</label>
                <input
                  id="shared-account" className="f-input" value={accountId}
                  onChange={(e) => setAccountId(e.target.value)} required
                />
                <span className="f-hint">
                  GSHK's single TPSI account with the Companies Registry — shared
                  by every user of the portal.
                </span>
              </div>

              <SecretField
                id="shared-tpsi-password"
                label="TPSI login password"
                hint={meta.tpsi_password_hint}
                value={password}
                onChange={setPassword}
                help="Authenticates the whole portal to TPSI — every user files under it. It never signs anything. Leave it untouched to keep the stored one."
              />

              <div className="f-group" style={{ marginBottom: 0 }}>
                <label className="f-label" htmlFor="shared-deposit">Deposit account number</label>
                <input
                  id="shared-deposit" className="f-input" value={depositAccount}
                  onChange={(e) => setDepositAccount(e.target.value)}
                />
                <span className="f-hint">
                  The account every filing fee is drawn from. NAR1 costs HK$105 per filing.
                </span>
              </div>
            </div>

            <div className="action-bar">
              <div className="ab-note">
                Changing this repoints every future filing GSHK makes.
              </div>
              <div className="ab-actions">
                <button type="submit" className="btn btn-action" disabled={saving}>
                  {saving ? 'Saving…' : isNew ? 'Save shared account' : 'Update shared account'}
                </button>
              </div>
            </div>
          </form>
        </div>

        <div>
          <ExpiryCard meta={meta} />
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
            <Meta label="Deposit account">
              {meta.deposit_account_no || <span className="td-muted">Not set</span>}
            </Meta>
            <Meta label="Password expires">
              {meta.tpsi_password_expires_at
                ? formatDate(meta.tpsi_password_expires_at)
                : <span className="td-muted">—</span>}
            </Meta>
            <Meta label="Last rotated">
              {meta.last_rotated_at
                ? formatDate(meta.last_rotated_at)
                : <span className="td-muted">Never</span>}
            </Meta>
          </div>

          <div className="reveal-note" style={{ lineHeight: 1.55 }}>
            Only a Super Admin can see or change this account. Holding{' '}
            <b>tpsi:write</b> lets a user file under it — it does not let them
            point every future filing at a different CR account.
          </div>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// The signed-in user's own e-Service signing credential — everyone
// ---------------------------------------------------------------------------

function MinePane({ canWrite, onNotice, onError }) {
  const [meta, setMeta] = useState(undefined)
  const [saving, setSaving] = useState(false)
  const [eserviceUserId, setEserviceUserId] = useState('')
  const [password, setPassword] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await api.get('/tpsi/credentials')
      setMeta(data || {})
      setEserviceUserId(data?.eservice_user_id || '')
      setPassword(null)
    } catch (e) {
      onError(e.message)
      setMeta({})
    }
  }, [onError])

  useEffect(() => { load() }, [load])

  if (meta === undefined) {
    return <div className="empty-state" style={{ padding: 32 }}>Loading your signing credentials…</div>
  }

  // An empty object is what the API returns when this user has no row at all.
  // The presenter account id is no longer part of the payload — see below.
  const isNew = Object.keys(meta).length === 0

  async function handleSave(e) {
    e.preventDefault()
    onError(null); onNotice(null)

    if (!eserviceUserId.trim()) {
      onError('Enter your e-Service user ID before saving.')
      return
    }

    /**
     * SIGNING CREDENTIALS ONLY. No `presentor_account_id`, no `tpsi_password`.
     *
     * Since BE-5 the CR login is the shared presenter record and `client_for()`
     * authenticates every call with it, so an ordinary user has no TPSI account
     * or password of their own — and must never be shown or asked for GSHK's.
     * The backend reads the shared record itself; both fields are optional on
     * CredentialIn/CredentialUpdateIn and `_UNSET`-guarded, so omitting them
     * leaves any legacy stored value untouched rather than clearing it.
     */
    const payload = {
      eservice_user_id: eserviceUserId.trim() || null,
    }
    // Untouched secrets are OMITTED, not sent as null: the backend reads a
    // present-but-null field as "clear this column".
    if (password !== null) payload.eservice_password = password || null

    setSaving(true)
    try {
      // POST for a first save, PUT for a change, so the audit trail says what
      // actually happened: TPSI_CRED_SET is "first stored", TPSI_CRED_ROTATE is
      // "replaced". The log is insert-only, so recording a first save as a
      // rotation of something that never existed could not be corrected later.
      const saved = isNew
        ? await api.post('/tpsi/credentials', payload)
        : await api.put('/tpsi/credentials', payload)
      setMeta(saved)
      setPassword(null)
      onNotice(isNew ? 'Signing credentials saved.' : 'Signing credentials updated.')
    } catch (e) {
      onError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleClear() {
    onError(null); onNotice(null); setSaving(true)
    try {
      // An explicit null CLEARS the column — that is the intent here, and the
      // only field mentioned, so nothing else is touched.
      const saved = await api.put('/tpsi/credentials', { eservice_password: null })
      setMeta(saved)
      setPassword(null)
      onNotice('Stored signing password removed.')
    } catch (e) {
      onError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="cr-scope mine">
        <div>
          <b>Yours alone.</b> Signing is a personal act and CR rejects a
          signature from a corporate account, so this credential is never shared
          — not with another user, and not with a Super Admin.
        </div>
      </div>

      <div className="detail-grid client-off">
        <div>
          <form onSubmit={handleSave}>
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Signing identity</div>
                  <div className="card-sub">Used when you sign a form yourself</div>
                </div>
              </div>

              <div className="reveal-note" style={{ color: 'var(--indigo)', background: 'var(--indigo-10)', marginBottom: 14 }}>
                <b>Two passwords, two jobs.</b> The shared TPSI password
                authenticates the portal. The e-Service password below signs.
                CR treats them differently.
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
                value={password}
                onChange={setPassword}
                help="Stored so you can sign as company secretary without re-typing it. A client director's password is never stored — they enter it at the moment of signing."
              />
            </div>

            {canWrite && (
              <div className="action-bar">
                <div className="ab-note">
                  Leave the password untouched to keep what is already stored.
                </div>
                <div className="ab-actions">
                  {meta.has_eservice_password && (
                    <button
                      type="button" className="btn btn-outline"
                      onClick={handleClear} disabled={saving}
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
          <div className="card mb-16">
            <div className="card-hdr"><div><div className="card-title">Status</div></div></div>
            <Meta label="Signing password">
              {meta.has_eservice_password
                ? <span style={{ color: 'var(--bang)' }}>Stored</span>
                : <span className="td-muted">Not set</span>}
            </Meta>
            <Meta label="e-Service user ID">
              {meta.eservice_user_id || <span className="td-muted">Not set</span>}
            </Meta>
            <Meta label="Last rotated">
              {meta.last_rotated_at
                ? formatDate(meta.last_rotated_at)
                : <span className="td-muted">Never</span>}
            </Meta>
          </div>

          <div className="reveal-note" style={{ lineHeight: 1.55 }}>
            Passwords are encrypted at rest. A stored password is shown{' '}
            <b>masked except its last 4 characters</b>, so you can tell which one
            is saved without it being readable. Only you see your own — never
            another user, never a Super Admin.
          </div>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------

/**
 * Which pane to show — the ONE place the admin-only rule is decided.
 *
 * Exported so the rule can be tested directly. It was previously enforced twice
 * (the initial tab value AND a guard in the render), and two redundant guards
 * mean neither is independently covered: a mutation test removing either one
 * left every assertion green, because the other silently carried it. One
 * authoritative answer is both simpler and actually testable.
 */
export function paneFor(isSuperAdmin, tab) {
  return isSuperAdmin && tab === 'shared' ? 'shared' : 'mine'
}

export default function CrCredentialsPage() {
  const { hasPermission, isSuperAdmin } = useAuth()
  const canWrite = isSuperAdmin || hasPermission('tpsi', 'write')

  // An ordinary user has one pane and never learns the shared tab exists.
  const [tab, setTab] = useState('shared')
  const pane = paneFor(isSuperAdmin, tab)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  function select(next) {
    setTab(next)
    setError(null)
    setNotice(null)
  }

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">CR Credentials</div>
          <div className="pg-sub">
            {isSuperAdmin
              ? <>GSHK files under <b>one shared</b> CR presenter account, maintained
                  by an admin. Your <b>e-Service signing</b> credentials stay your own.</>
              : <>Your own e-Service signing credentials. GSHK files under a shared
                  CR account that an admin maintains.</>}
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

      {/* No tab bar for an ordinary user: one pane, and a single-tab tab bar is
          noise. The shared pane is absent for them, not disabled. */}
      {isSuperAdmin && (
        <div className="cr-tabs" role="tablist" aria-label="Credential scope">
          <button
            className={`cr-tab ${pane === 'shared' ? 'active' : ''}`}
            role="tab" aria-selected={pane === 'shared'}
            onClick={() => select('shared')}
          >
            CR/TPSI account · shared
          </button>
          <button
            className={`cr-tab ${pane === 'mine' ? 'active' : ''}`}
            role="tab" aria-selected={pane === 'mine'}
            onClick={() => select('mine')}
          >
            My e-Service signing
          </button>
        </div>
      )}

      {pane === 'shared'
        ? <SharedPane onNotice={setNotice} onError={setError} />
        : <MinePane canWrite={canWrite} onNotice={setNotice} onError={setError} />}
    </>
  )
}
