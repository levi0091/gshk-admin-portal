import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'

const ACTION_LABELS = {
  CASE_STATUS_CHANGED: 'Case status changed',
  CASE_FIELD_UPDATED: 'Case field updated',
  AML_STATUS_CHANGED: 'AML status changed',
  DOCUMENT_GENERATED: 'Document generated',
  EMAIL_SENT: 'Email sent',
  TPSI_SUBMISSION_ATTEMPTED: 'TPSI submission attempted',
  TPSI_SUBMISSION_SUCCESS: 'TPSI submission succeeded',
  TPSI_SUBMISSION_FAILED: 'TPSI submission failed',
  CLIENT_APPROVAL_RECEIVED: 'Client approval received',
  USER_LOGIN: 'User signed in',
  USER_DEACTIVATED: 'User deactivated',
  AUDIT_TRAIL_VIEWED: 'Audit trail viewed',
}

function formatTs(iso) {
  return new Date(iso).toLocaleString('en-HK', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Hong_Kong',
  })
}

function detail(entry) {
  if (entry.action_type === 'CASE_FIELD_UPDATED' && entry.after_state) {
    const field = (entry.after_state.field || '').replace(/_/g, ' ')
    return `${field}: "${entry.before_state?.old ?? '—'}" → "${entry.after_state.new ?? '—'}"`
  }
  if (entry.action_type === 'CASE_STATUS_CHANGED' && entry.after_state) {
    return `→ ${entry.after_state.new ?? entry.after_state.status ?? ''}`
  }
  if (entry.action_type?.startsWith('TPSI_') && entry.metadata?.endpoint) {
    return entry.metadata.endpoint
  }
  return ''
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/audit/')
      .then(data => setEntries(data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Audit Log</div>
          <div className="pg-sub">All system activity — read-only · Showing last 200 entries</div>
        </div>
      </div>

      <div className="tbl-wrap">
        {error ? (
          <div style={{ padding: '24px', background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13, margin: 0 }}>
            Failed to load audit log: {error}
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 170 }}>Time (HKT)</th>
                <th>Action</th>
                <th>User</th>
                <th>Case</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', color: 'var(--t-muted)', padding: 32 }}>
                    Loading…
                  </td>
                </tr>
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', color: 'var(--t-muted)', padding: 32 }}>
                    No audit events recorded yet.
                  </td>
                </tr>
              ) : entries.map(e => (
                <tr key={e.id}>
                  <td style={{ fontSize: 12, color: 'var(--t-muted)', whiteSpace: 'nowrap' }}>
                    {formatTs(e.created_at)}
                  </td>
                  <td>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--t-head)' }}>
                      {ACTION_LABELS[e.action_type] || e.action_type}
                    </span>
                  </td>
                  <td style={{ fontSize: 13, color: 'var(--t-body)' }}>
                    {e.user_display_name || '—'}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--t-muted)', fontFamily: 'monospace' }}>
                    {e.case_id ? e.case_id.slice(0, 8) + '…' : '—'}
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--t-muted)', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {detail(e)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
