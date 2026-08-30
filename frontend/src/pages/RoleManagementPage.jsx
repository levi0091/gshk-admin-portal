import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'

// A permission entry is { value, label } — value is the module permission the
// backend checks ('read'/'write'/'delete'), label is what the user sees. They
// differ where "Edit" reads better than the literal 'write'.
// A permission entry is { value, label } — value is the module permission the
// backend checks ('read'/'write'/'delete'), label is what the user sees. They
// differ where "Edit" reads better than the literal 'write'.
const READ = { value: 'read', label: 'Read' }
const EDIT = { value: 'write', label: 'Edit' }
const DELETE = { value: 'delete', label: 'Delete' }
const SUBMIT = { value: 'submit', label: 'File with CR' }

/**
 * Every module the backend actually gates on, with the levels it accepts.
 *
 * This list was three modules long while the database had six — so `nar1`,
 * `tpsi` and `documents` could not be granted through the UI at all, and
 * nobody but a Super Admin could ever see a NAR1 case, let alone file one.
 *
 * `hint` says what the level MEANS for the work, because "write" on its own
 * does not tell an admin that it is the difference between watching a
 * statutory filing and driving it.
 */
const MODULES = [
  { id: 'companies', label: 'Companies', permissions: [READ, EDIT] },
  { id: 'persons', label: 'Persons', permissions: [READ, EDIT] },
  {
    id: 'nar1',
    label: 'NAR1 cases',
    permissions: [READ, EDIT],
    hint: 'Read shows NAR1 cases on the Post-incorporation dashboard. '
        + 'Edit is needed to open a case and to move one forward.',
  },
  {
    id: 'tpsi',
    label: 'Companies Registry filing',
    permissions: [READ, EDIT, SUBMIT],
    hint: 'Read sees the fee and balance. Edit validates and signs. '
        + 'File with CR spends from the deposit account and cannot be undone — '
        + 'grant it deliberately.',
  },
  { id: 'documents', label: 'Documents', permissions: [READ, EDIT, DELETE] },
  { id: 'audit_trail', label: 'Audit Trail', permissions: [READ] },
]

function permSet(role) {
  return new Set(
    (role.role_permissions || []).map(p => `${p.module}:${p.permission}`)
  )
}

function RoleModal({ role, onClose, onSaved }) {
  const existing = role ? permSet(role) : new Set()
  const [name, setName] = useState(role?.name || '')
  const [perms, setPerms] = useState(existing)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function toggle(module, permission) {
    const key = `${module}:${permission}`
    setPerms(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  function permissionsPayload() {
    return Array.from(perms).map(key => {
      const [module, permission] = key.split(':')
      return { module, permission }
    })
  }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (role) {
        await api.patch(`/roles/${role.id}`, { name, permissions: permissionsPayload() })
      } else {
        await api.post('/roles/', { name, permissions: permissionsPayload() })
      }
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
          <span className="modal-title">{role ? 'Edit Role' : 'Create Role'}</span>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="f-group">
              <label className="f-label">Role Name <span className="f-req">*</span></label>
              <input className="f-input" required value={name} onChange={e => setName(e.target.value)} placeholder="e.g. company_reviewer" disabled={role?.name === 'super_admin'} />
              <span className="f-hint">Use snake_case. e.g. compliance_staff</span>
            </div>

            <div>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--indigo)', marginBottom: 10 }}>
                Module Permissions
              </div>
              {MODULES.map(mod => (
                <div key={mod.id} style={{ background: 'var(--indigo-5)', borderRadius: 8, padding: 14, marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--t-head)', marginBottom: mod.hint ? 4 : 10 }}>{mod.label}</div>
                  {mod.hint && (
                    <div style={{ fontSize: 11, color: 'var(--t-muted)', lineHeight: 1.5, marginBottom: 10 }}>
                      {mod.hint}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {mod.permissions.map(perm => {
                      const key = `${mod.id}:${perm.value}`
                      return (
                        <label key={perm.value} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                          <input
                            type="checkbox"
                            checked={perms.has(key)}
                            onChange={() => toggle(mod.id, perm.value)}
                            style={{ width: 15, height: 15, accentColor: 'var(--indigo)' }}
                            disabled={role?.name === 'super_admin'}
                          />
                          <span style={{ color: 'var(--t-body)' }}>{perm.label}</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>

            {error && (
              <div style={{ background: '#FEE2E2', border: '1px solid #FCA5A5', borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#B91C1C' }}>
                {error}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={loading || role?.name === 'super_admin'}>
              {loading ? 'Saving…' : role ? 'Save Changes' : 'Create Role'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function RoleManagementPage() {
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [editTarget, setEditTarget] = useState(null)
  const [showModal, setShowModal] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const r = await api.get('/roles/')
      setRoles(r)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function openEdit(role) { setEditTarget(role); setShowModal(true) }
  function openCreate() { setEditTarget(null); setShowModal(true) }
  function closeModal() { setShowModal(false); setEditTarget(null) }

  function permSummary(role) {
    const perms = role.role_permissions || []
    if (role.name === 'super_admin') return 'Full access — all modules'
    if (perms.length === 0) return 'No permissions assigned'
    return perms.map(p => `${p.module} (${p.permission})`).join(', ')
  }

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Role Management</div>
          <div className="pg-sub">Define roles and module-permission assignments</div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-primary" onClick={openCreate}>
            <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 16 16"><path d="M8 1v14M1 8h14"/></svg>
            New Role
          </button>
        </div>
      </div>

      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Role Name</th>
              <th>Permissions</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={3} style={{ textAlign: 'center', color: 'var(--t-muted)', padding: 24 }}>Loading…</td></tr>
            ) : roles.map(r => (
              <tr key={r.id}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, color: 'var(--t-head)' }}>{r.name}</span>
                    {r.name === 'super_admin' && (
                      <span className="badge b-admin" style={{ fontSize: 10 }}>Super Admin</span>
                    )}
                  </div>
                </td>
                <td style={{ color: 'var(--t-muted)', fontSize: 12 }}>{permSummary(r)}</td>
                <td>
                  <button className="btn btn-outline btn-sm" onClick={() => openEdit(r)}>
                    {r.name === 'super_admin' ? 'View' : 'Edit'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <RoleModal
          role={editTarget}
          onClose={closeModal}
          onSaved={load}
        />
      )}
    </>
  )
}
