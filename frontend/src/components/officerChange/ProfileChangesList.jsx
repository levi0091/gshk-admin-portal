import { Link } from 'react-router-dom'

function pathOf(target) {
  if (!target?.id) return null
  return target.kind === 'person' ? `/persons/${target.id}` : `/companies/${target.id}`
}

/**
 * What filing writes to the profiles and where the supporting documents go
 * (answers 11 and 13): in the future tense at Submission, in the past tense at
 * Confirmation — the same list, so the operator can see it happened as stated.
 */
export default function ProfileChangesList({ changes = [], documents = [], done = false }) {
  const byDestination = new Map()
  for (const doc of documents) {
    const key = `${doc.destination?.owner_kind}:${doc.destination?.owner_id}`
    if (!byDestination.has(key)) byDestination.set(key, { destination: doc.destination, docs: [] })
    byDestination.get(key).docs.push(doc)
  }
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-title">{done ? 'Profile updated' : 'What filing will update'}</div>
      {changes.length === 0
        ? <div className="f-hint">Nothing on the profiles changes.</div>
        : (
          <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
            {changes.map(c => (
              <li key={c.entry_id}>
                {c.text}
                {c.target && pathOf(c.target) && (
                  <> — <Link to={pathOf(c.target)}>{c.target.name}</Link></>
                )}
              </li>
            ))}
          </ul>
        )}
      <div className="card-title" style={{ marginTop: 14 }}>
        {done ? 'Supporting documents saved' : 'Supporting documents'}
      </div>
      {byDestination.size === 0
        ? <div className="f-hint">No supporting documents were uploaded.</div>
        : [...byDestination.values()].map(({ destination, docs }) => {
          const path = destination?.owner_kind === 'person' ? `/persons/${destination.owner_id}`
            : destination?.owner_id ? `/companies/${destination.owner_id}` : null
          return (
            <div key={`${destination?.owner_kind}:${destination?.owner_id}`} style={{ marginTop: 6 }}>
              {docs.map(d => d.file_name).join(', ')}{' '}
              {done && docs.every(d => d.filed) ? 'saved to ' : 'will be saved to '}
              {path ? <Link to={path}>{destination?.name}</Link> : destination?.name}
              {done && docs.some(d => d.error) && (
                <span className="td-muted"> — not yet saved: {docs.filter(d => !d.filed).map(d => d.file_name).join(', ')}</span>
              )}
            </div>
          )
        })}
    </div>
  )
}
