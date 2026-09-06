import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'
import { formatDateTime } from '../lib/format.js'

const ACTION_LABELS = {
  CASE_STATUS_CHANGED: 'Case status changed',
  CASE_FIELD_UPDATED: 'Case field updated',
  AML_STATUS_CHANGED: 'AML status changed',
  DOCUMENT_GENERATED: 'Document generated',
  EMAIL_SENT: 'Email sent',
  TPSI_AUTH: 'CR session opened',
  TPSI_FILING_CREATED: 'CR filing prepared',
  TPSI_VALIDATE: 'CR form validated',
  TPSI_SIGN: 'CR form signed',
  TPSI_EDRIVE: 'CR form sent to e-Drive',
  TPSI_PREVIEWED: 'CR submission previewed',
  TPSI_BALANCE_CHECK: 'CR deposit balance checked',
  TPSI_STATUS: 'CR case status enquired',
  TPSI_CRED_SET: 'CR credential set',
  TPSI_CRED_ROTATE: 'CR credential rotated',
  TPSI_PW_CHANGE: 'CR password changed',
  TPSI_SUBMISSION_ATTEMPTED: 'TPSI submission attempted',
  TPSI_SUBMISSION_SUCCESS: 'TPSI submission succeeded',
  TPSI_SUBMISSION_FAILED: 'TPSI submission failed',
  CLIENT_APPROVAL_RECEIVED: 'Client approval received',
  NAR1_MANUAL_SIGN_UPLOADED: 'Wet-signed NAR1 uploaded',
  NAR1_MANUAL_RECEIPT_ENTERED: 'Off-portal CR receipt recorded',
  NAR1_MANUAL_SUBMISSION_RECORDED: 'Off-portal filing recorded',
  NAR1_CASE_CLOSED: 'Case closed',
  USER_LOGIN: 'User signed in',
  USER_DEACTIVATED: 'User deactivated',
}

const formatTs = formatDateTime

function FieldDiff({ before, after }) {
  if (!before || !after) return null
  const field = after.field || before.field || 'field'
  const label = field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return (
    <div className="tl-diff">
      <strong>{label}:</strong>{' '}
      <span className="diff-old">&ldquo;{before.old ?? '—'}&rdquo;</span>
      {' → '}
      <span className="diff-new">&ldquo;{after.new ?? '—'}&rdquo;</span>
    </div>
  )
}

function AuditEntry({ entry }) {
  const label = ACTION_LABELS[entry.action_type] || entry.action_type

  return (
    <div className="tl-item">
      <div className="tl-dot ev">
        <svg width="8" height="8" viewBox="0 0 8 8">
          <circle cx="4" cy="4" r="3" fill="var(--indigo)"/>
        </svg>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span className="tl-action">{label}</span>
          <span style={{ fontSize: 12, color: 'var(--t-muted)' }}>
            by <strong style={{ color: 'var(--t-body)' }}>{entry.user_display_name}</strong>
          </span>
        </div>
        <div className="tl-timestamp">{formatTs(entry.created_at)}</div>

        {entry.action_type === 'CASE_FIELD_UPDATED' && (
          <FieldDiff before={entry.before_state} after={entry.after_state} />
        )}
        {entry.action_type === 'CASE_STATUS_CHANGED' && entry.after_state && (
          <div className="tl-diff">
            Status changed to <strong>{entry.after_state.new ?? entry.after_state.status}</strong>
          </div>
        )}
        {entry.action_type?.startsWith('TPSI_') && entry.metadata && (
          <div className="tl-diff">
            Endpoint: <code style={{ background: 'var(--indigo-10)', padding: '1px 5px', borderRadius: 3, fontSize: 11 }}>
              {entry.metadata.endpoint}
            </code>
            {entry.metadata.response_status && (
              <> · Status: <strong>{entry.metadata.response_status}</strong></>
            )}
            {entry.metadata.error_code && (
              <> · Error: <span style={{ color: '#C53030' }}>{entry.metadata.error_code}</span></>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function AuditTrailTab({ caseId }) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!caseId) return
    setLoading(true)
    api.get(`/cases/${caseId}/audit`)
      .then(data => setEntries(data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [caseId])

  if (loading) return (
    <div style={{ padding: 24, textAlign: 'center', color: 'var(--t-muted)' }}>
      Loading audit trail…
    </div>
  )

  if (error) return (
    <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
      Failed to load audit trail: {error}
    </div>
  )

  if (entries.length === 0) return (
    <div className="empty-state">No audit events recorded for this case yet.</div>
  )

  return (
    <div style={{ padding: '4px 0' }}>
      <div className="timeline">
        {entries.map(entry => (
          <AuditEntry key={entry.id} entry={entry} />
        ))}
      </div>
    </div>
  )
}
