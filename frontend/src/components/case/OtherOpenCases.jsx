import { Link } from 'react-router-dom'
import { casePath } from '../officerChange/workflow.js'

/**
 * The company's other filings still open, said at Submission (Jacqueline AQ3:
 * "an alert when there is an open ND2A/NAR1 case pending as a reminder when
 * we submit anything to CR"; BQ1: NAR1 and ND2B usually go together).
 *
 * A reminder, never a gate: the two are separate submissions to CR and either
 * may rightly go first. Shown on NAR1's Submission stage and on ND2A/ND2B's.
 */
export default function OtherOpenCases({ cases }) {
  const rows = Array.isArray(cases) ? cases : []
  if (rows.length === 0) return null
  return (
    <div className="alert al-info mb-16" role="status">
      <span className="al-icon">ℹ</span>
      <div className="al-body">
        <b>This company has other filings open.</b> If this filing should reflect them, or
        go to the Companies Registry with them, deal with them first:
        <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          {rows.map(c => (
            <li key={c.id}>
              <Link to={casePath(c)}>{c.case_type} {c.case_no}</Link>
              {c.workflow_status?.label ? ` — ${c.workflow_status.label}` : ''}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
