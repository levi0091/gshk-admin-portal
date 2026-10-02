/**
 * The company rules, as the backend evaluated them (`rules.evaluate`):
 * a rule that fails blocks sending to the client; a notice never does.
 */
export default function RulesPanel({ rules }) {
  if (!rules) return null
  const checks = rules.checks || []
  const failing = checks.filter(c => !c.ok)
  return (
    <div className="card" style={{ marginTop: 16 }} aria-label="Company rules">
      <div className="card-hdr">
        <div>
          <div className="card-title">Company rules</div>
          {rules.summary && <div className="card-sub">{rules.summary}</div>}
        </div>
        {rules.blocking
          ? <span className="badge b-client-rejected">Breach — cannot send</span>
          : <span className="badge b-live">{failing.length ? 'OK, with notes' : 'All rules met'}</span>}
      </div>
      <ul className="oc-rules">
        {checks.map(c => {
          const tone = c.ok ? 'ok' : c.level === 'notice' ? 'notice' : 'bad'
          return (
            <li key={c.code} className={`oc-rule ${tone}`} data-code={c.code}>
              <span className="oc-rule-mark" aria-hidden="true">
                {tone === 'ok' ? '✓' : tone === 'notice' ? '!' : '✕'}
              </span>
              <span>{c.text}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
