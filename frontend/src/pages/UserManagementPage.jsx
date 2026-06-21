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
  const [form, setForm] = useState({ display_name: '', email: '', role_id: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function set(field, val) { setForm(f => ({ ...f, [field]: val })) }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.post('/users/', form)
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
            <div className="f-group">
              <label className="f-label">Temporary Password <span className="f-req">*</span></label>
              <input className="f-input" type="password" required value={form.password} onChange={e => set('password', e.target.value)} placeholder="Min 8 characters" />
              <span className="f-hint">Share with user via secure channel. They can reset from login screen.</span>
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
  const { profile } = useAuth()
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
                    {u.is_active && u.id !== profile?.id && (
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
