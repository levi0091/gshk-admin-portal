import { Link } from 'react-router-dom'
import './entryPoints.css'

/**
 * The unfinished officer-change case naming this officer, or null.
 *
 * `cases` is `GET /officer-changes/pending?entity_id=…`. An entry names an
 * officer by its officer row (a director tile row's own id) or, for the
 * Secretary tile — which reads the secretary register and so carries a
 * different id — by the same person or company in the same capacity.
 */
export function pendingFor(cases, { officerId, personId, corporateEntityId, capacity } = {}) {
  for (const c of cases || []) {
    const hit = (c.entries || []).find(e =>
      (officerId && e.officer_id === officerId)
      || (e.capacity === capacity && (
        (personId && e.person_id === personId)
        || (corporateEntityId && e.corporate_entity_id === corporateEntityId))))
    if (hit) return { case: c, entry: hit }
  }
  return null
}

const WHAT = { cessation: 'Cessation', appointment: 'Appointment', change: 'Change' }

/**
 * "Cessation pending · ND2A-2026-0001" beside an officer's name: the profile
 * still shows them as they are, because CR has not been told yet, and this is
 * how a reader knows a filing about them is already under way. A link, so the
 * case is one click from the row that prompted the question.
 */
export default function PendingChangeChip({ pending }) {
  if (!pending) return null
  const { case: c, entry } = pending
  return (
    <Link className="ep-chip" to={`/officer-changes/${c.id}`}
          title={`Open ${c.case_no || 'the case'}`}>
      <span className="ep-chip-dot" aria-hidden="true" />
      {WHAT[entry.kind] || 'Change'} pending
      <span className="ep-chip-no">{c.case_no || c.case_type}</span>
    </Link>
  )
}
