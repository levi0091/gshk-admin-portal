import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../context/AuthContext.jsx'

function StatusBadge({ isActive }) {
  return (
    <span className={`badge ${isActive ? 'b-active' : 'b-inactive'}`}>
      {isActive ? 'Active' : 'Inactive'}
    </span>
  )
}

function AddUserModal({ roles, onClose, onCreated }) {
  // THREE FIELDS. The password box is GONE, not disabled (spec §7): an
  // administrator no longer chooses a colleague's password. The portal
  // generates one, emails it, and the account cannot do anything until its
  // owner replaces it.
  const [form, setForm] = useState({ display_name: '', email: '', role_id: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [warning, setWarning] = useState('')

  function set(field, val) { setForm(f => ({ ...f, [field]: val })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setWarning('')
    setLoading(true)
    try {
      const created = await api.post('/users/', form)
      // THE ACCOUNT EXISTS EITHER WAY. A welcome email that failed leaves a
      // real user in Supabase Auth who has no password and no way to ask for
      // one, so this cannot be silent — but it is not an error either, because
      // retrying the creation would collide on the email address.
      // ON A TEST DEPLOYMENT THE MAIL IS REDIRECTED to the four hardcoded
      // addresses in `email_service.TEST_RECIPIENTS`. The account is real and
      // it is locked to `must_change_password`, so unless the new user IS one
      // of those four they can never sign in — and nothing else on this screen
      // would say why.
      if (created?.welcome_email_redirected) {
        setWarning(
          'The account was created, but this is a test environment: the '
          + 'welcome email went to the test mailboxes, not to '
          + `${form.email}. They cannot sign in until somebody passes them the `
          + 'password from that mailbox.')
        onCreated()
        return
      }
      if (created?.welcome_email_sent === false) {
        setWarning(
          'The account was created, but the welcome email did not send'
          + (created.welcome_email_error ? ` — ${created.welcome_email_error}` : '')
          + '. They cannot sign in until they have their password: deactivate '
          + 'this account and create it again once mail is working.')
        onCreated()
        return
      }
      onCreated()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <span className="modal-title">Add User</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="f-group">
              <label className="f-label">Display Name <span className="f-req">*</span></label>
              <input className="f-input" required value={form.display_name} onChange={e => set('display_name', e.target.value)} placeholder="e.g. Sarah Wong" />
            </div>
            <div className="f-group">
              <label className="f-label">Email Address <span className="f-req">*</span></label>
              <input className="f-input" type="email" required value={form.email} onChange={e => set('email', e.target.value)} />
            </div>
            <div className="f-group">
              <label className="f-label">Role <span className="f-req">*</span></label>
              <select className="f-select" required value={form.role_id} onChange={e => set('role_id', e.target.value)}>
                <option value="">Select role…</option>
                {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div className="f-hint">
              G-FlowDesk emails them a password and asks them to choose their
              own the first time they sign in. Nobody else ever sees it.
            </div>
            {warning && (
              <div style={{ background: '#FEF0EB', border: '1px solid #F36C32', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#8A3410' }}>
                {warning}
              </div>
            )}
            {error && (
              <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C' }}>
                {error}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {warning ? 'Close' : 'Cancel'}
            </button>
            <button type="submit" className="btn btn-primary"
                    disabled={loading || Boolean(warning)}>
              {loading ? 'Creating…' : 'Create User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function EditUserModal({ user, roles, onClose, onSaved }) {
  const [form, setForm] = useState({ display_name: user.display_name, role_id: user.role_id })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function set(field, val) { setForm(f => ({ ...f, [field]: val })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.patch(`/users/${user.id}`, form)
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <span className="modal-title">Edit User</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="f-group">
              <label className="f-label">Display Name <span className="f-req">*</span></label>
              <input className="f-input" required value={form.display_name} onChange={e => set('display_name', e.target.value)} />
            </div>
            <div className="f-group">
              <label className="f-label">Role <span className="f-req">*</span></label>
              <select className="f-select" required value={form.role_id} onChange={e => set('role_id', e.target.value)}>
                {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            {error && (
              <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C' }}>
                {error}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function ResetPasswordModal({ user, isSelf, onClose, onReset }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  async function confirm() {
    setError('')
    setLoading(true)
    try {
      // THE RESPONSE CARRIES NO PASSWORD, deliberately — an administrator
      // resets an account, they do not learn how to sign in as it. What comes
      // back is whether the mail carrying it actually went.
      setResult(await api.post(`/users/${user.id}/reset-password`, {}))
      onReset()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Everything below the first branch is the AFTER state. The password has
  // already changed by the time any of it renders, so none of it offers to
  // cancel — the only remaining question is whether the mail arrived.
  const sent = result && result.reset_email_sent && !result.reset_email_redirected
  const redirected = result && result.reset_email_redirected
  const failed = result && result.reset_email_sent === false

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <span className="modal-title">Reset Password</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {!result && (
            <>
              <p style={{ fontSize: 13, color: 'var(--t-body)', lineHeight: 1.6, margin: 0 }}>
                Reset the password for <strong>{user.display_name}</strong>?
                G-FlowDesk will email a new temporary password and require them
                to choose their own the next time they sign in. Their current
                password stops working immediately.
              </p>

              {/* THE ADDRESS, SET AS A SPECIMEN. Two rows in this table can
                  carry the same display name, and the whole point of the
                  confirmation is that the administrator resets the account
                  they meant to — so the identifier that is actually unique is
                  the one worth reading, and it does not belong buried in the
                  sentence above. */}
              <div style={{
                background: 'var(--indigo-5)', border: '1px solid var(--border)',
                borderRadius: 6, padding: '12px 14px', marginTop: 14,
              }}>
                <div style={{
                  fontSize: 11, fontWeight: 600, letterSpacing: '.04em',
                  textTransform: 'uppercase', color: 'var(--t-muted)', marginBottom: 4,
                }}>
                  The new password will be emailed to
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--t-head)', wordBreak: 'break-all' }}>
                  {user.email}
                </div>
              </div>

              {isSelf && (
                <div style={{ background: '#FEF0EB', border: '1px solid #F36C32', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#8A3410', marginTop: 14 }}>
                  This is your own account. You will be asked to choose a new
                  password straight away, and nothing else in the portal opens
                  until you do.
                </div>
              )}
            </>
          )}

          {sent && (
            <p style={{ fontSize: 13, color: 'var(--t-body)', lineHeight: 1.6, margin: 0 }}>
              Done. A temporary password is on its way to <strong>{result.email}</strong>.
              Nobody else can read it — it exists only in that mailbox.
              {result.must_change_password === false && (
                <> They were <strong>not</strong> required to change it on sign-in:
                that flag did not save. Reset again to retry.</>
              )}
            </p>
          )}

          {/* The test-environment lock (email_service.TEST_RECIPIENTS) sends
              every message to four hardcoded mailboxes. The reset is real and
              the old password is gone, so unless this user is one of those
              four they are now locked out — and nothing else on this screen
              would say why. */}
          {redirected && (
            <div style={{ background: '#FEF0EB', border: '1px solid #F36C32', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#8A3410' }}>
              The password was reset, but this is a test environment: the email
              went to the test mailboxes, not to {result.email}. They cannot
              sign in until somebody passes them the password from that mailbox.
            </div>
          )}

          {failed && (
            <div style={{ background: '#FEF0EB', border: '1px solid #F36C32', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#8A3410' }}>
              The password was reset, but the email did not send
              {result.reset_email_error ? ` — ${result.reset_email_error}` : ''}.
              Their old password has already stopped working, so they are locked
              out until this is delivered: press Reset Password again once mail
              is working.
            </div>
          )}

          {error && (
            <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C', marginTop: 14 }}>
              {error}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose}>
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button className="btn btn-primary" disabled={loading} onClick={confirm}>
              {loading ? 'Resetting…' : 'Reset Password'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function DeactivateModal({ user, onClose, onDeactivated }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setError('')
    setLoading(true)
    try {
      await api.patch(`/users/${user.id}/deactivate`, {})
      onDeactivated()
      onClose()
    } catch (err) {
      // It used to close on failure too — `finally` without a `catch` — so a
      // refused deactivation looked exactly like a successful one until the
      // row reloaded still Active.
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <span className="modal-title">Deactivate User</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13, color: 'var(--t-body)', lineHeight: 1.6 }}>
            Are you sure you want to deactivate <strong>{user.display_name}</strong>?
            They will immediately lose access to the portal, and their sign-in
            is disabled in Supabase Auth as well.
          </p>
          {/* THE OLD COPY SAID "this can be reversed by reassigning a role",
              which was not true of anything the portal did: Edit writes the
              role and the display name and has never touched `is_active`, and
              nothing lifted the Auth ban. Naming the actual button is the
              point — an administrator needs to know the undo exists BEFORE
              pressing this, not after. */}
          <p className="confirm-note">
            Reversible: the row keeps its <b>Reactivate</b> button, which
            restores access and lifts the Auth ban.
          </p>
          {error && (
            <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C', marginTop: 14 }}>
              {error}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" disabled={loading} onClick={confirm}>
            {loading ? 'Deactivating…' : 'Deactivate'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * The undo deactivation never had.
 *
 * Both halves matter and only one of them is visible: `users.is_active` is what
 * this portal refuses on, and the Supabase Auth ban is what refuses the sign-in
 * itself. The backend lifts the ban FIRST and only then marks the row active,
 * so a failure leaves the account honestly deactivated rather than showing
 * Active beside a login that still does not work.
 */
function ReactivateModal({ user, onClose, onReactivated }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setError('')
    setLoading(true)
    try {
      await api.patch(`/users/${user.id}/reactivate`, {})
      onReactivated()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <span className="modal-title">Reactivate User</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13, color: 'var(--t-body)', lineHeight: 1.6, margin: 0 }}>
            Restore portal access for <strong>{user.display_name}</strong>? Their
            role and permissions come back exactly as they were, and their
            existing password still works.
          </p>

          {/* THE ADDRESS, SET AS A SPECIMEN — the same reason the reset dialog
              does it. Two rows can carry the same display name, and this is
              the identifier that is actually unique. */}
          <div style={{
            background: 'var(--indigo-5)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '12px 14px', marginTop: 14,
          }}>
            <div style={{
              fontSize: 11, fontWeight: 600, letterSpacing: '.04em',
              textTransform: 'uppercase', color: 'var(--t-muted)', marginBottom: 4,
            }}>
              Account being restored
            </div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--t-head)', wordBreak: 'break-all' }}>
              {user.email || '— no email on record —'}
            </div>
          </div>

          <p className="confirm-note" style={{ marginTop: 14 }}>
            If they have forgotten their password, use <b>Reset password</b>
            afterwards — that button is hidden while an account is deactivated,
            because a password mailed to a banned account cannot be used.
          </p>

          {error && (
            <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C', marginTop: 14 }}>
              {error}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={loading} onClick={confirm}>
            {loading ? 'Reactivating…' : 'Reactivate'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function UserManagementPage() {
  const { profile } = useAuth()
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [deactivateTarget, setDeactivateTarget] = useState(null)
  const [reactivateTarget, setReactivateTarget] = useState(null)
  const [resetTarget, setResetTarget] = useState(null)

  async function load() {
    setLoading(true)
    try {
      const [u, r] = await Promise.all([api.get('/users/'), api.get('/roles/')])
      setUsers(u)
      setRoles(r)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">User Management</div>
          <div className="pg-sub">Manage portal user accounts and role assignments</div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
            <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 16 16"><path d="M8 1v14M1 8h14"/></svg>
            Add User
          </button>
        </div>
      </div>

      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--t-muted)', padding: 24 }}>Loading…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={5}><div className="empty-state">No users yet. Add one above.</div></td></tr>
            ) : users.map(u => (
              <tr key={u.id}>
                <td style={{ fontWeight: 600, color: 'var(--t-head)' }}>{u.display_name}</td>
                <td style={{ color: 'var(--t-muted)', fontSize: 12 }}>{u.email}</td>
                <td>
                  <span className="tag"
                    style={u.roles?.name === 'super_admin' ? { background: 'var(--carrot-10)', color: 'var(--carrot)' } : {}}>
                    {u.roles?.name ?? '—'}
                  </span>
                </td>
                <td><StatusBadge isActive={u.is_active} /></td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-outline btn-sm" onClick={() => setEditTarget(u)}>
                      Edit
                    </button>
                    {/* Offered for super admins too, unlike Deactivate: a
                        reset does not remove anybody's access, and the account
                        that can file statutory returns is the one most worth
                        being able to recover. Hidden for deactivated accounts,
                        which are banned in Auth — the backend refuses those
                        with a 409, and a button that always fails is worse
                        than no button. */}
                    {u.is_active && (
                      <button className="btn btn-ghost btn-sm" onClick={() => setResetTarget(u)}>
                        Reset password
                      </button>
                    )}
                    {u.is_active && u.roles?.name !== 'super_admin' && (
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ color: '#C53030' }}
                        onClick={() => setDeactivateTarget(u)}
                      >
                        Deactivate
                      </button>
                    )}
                    {/* Offered for super admins too, unlike Deactivate. That
                        rule protects the LAST super admin from being locked
                        out; it is not a reason to leave one that is already
                        deactivated stranded — and Harry Lo, a deactivated
                        super_admin, is exactly that row on DEV. */}
                    {!u.is_active && (
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ color: 'var(--bang)' }}
                        onClick={() => setReactivateTarget(u)}
                      >
                        Reactivate
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <AddUserModal
          roles={roles.filter(r => r.name !== 'super_admin')}
          onClose={() => setShowAdd(false)}
          onCreated={load}
        />
      )}
      {editTarget && (
        <EditUserModal
          user={editTarget}
          roles={roles}
          onClose={() => setEditTarget(null)}
          onSaved={load}
        />
      )}
      {resetTarget && (
        <ResetPasswordModal
          user={resetTarget}
          isSelf={Boolean(profile?.id) && profile.id === resetTarget.id}
          onClose={() => setResetTarget(null)}
          onReset={load}
        />
      )}
      {deactivateTarget && (
        <DeactivateModal
          user={deactivateTarget}
          onClose={() => setDeactivateTarget(null)}
          onDeactivated={load}
        />
      )}
      {reactivateTarget && (
        <ReactivateModal
          user={reactivateTarget}
          onClose={() => setReactivateTarget(null)}
          onReactivated={load}
        />
      )}
    </>
  )
}
