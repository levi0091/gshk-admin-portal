import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'

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

function DeactivateModal({ user, onClose, onDeactivated }) {
  const [loading, setLoading] = useState(false)

  async function confirm() {
    setLoading(true)
    try {
      await api.patch(`/users/${user.id}/deactivate`, {})
      onDeactivated()
      onClose()
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
            Are you sure you want to deactivate <strong>{user.display_name}</strong>? They will immediately lose access to the portal. This can be reversed by reassigning a role.
          </p>
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

export default function UserManagementPage() {
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [deactivateTarget, setDeactivateTarget] = useState(null)

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
                    {u.is_active && u.roles?.name !== 'super_admin' && (
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ color: '#C53030' }}
                        onClick={() => setDeactivateTarget(u)}
                      >
                        Deactivate
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
      {deactivateTarget && (
        <DeactivateModal
          user={deactivateTarget}
          onClose={() => setDeactivateTarget(null)}
          onDeactivated={load}
        />
      )}
    </>
  )
}
