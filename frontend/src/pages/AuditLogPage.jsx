export default function AuditLogPage() {
  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Audit Log</div>
          <div className="pg-sub">All system activity — read-only</div>
        </div>
      </div>

      <div className="tbl-wrap">
        <div style={{ padding: '48px 24px', textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🕐</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--t-head)', marginBottom: 6 }}>
            Coming soon
          </div>
          <div style={{ fontSize: 13, color: 'var(--t-muted)', maxWidth: 360, margin: '0 auto' }}>
            The global Audit Log (PBI-11 v2) is in the build queue. Per-case audit trails are already
            available inside each case detail view.
          </div>
        </div>
      </div>
    </>
  )
}
