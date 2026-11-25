/**
 * A person's Identity Documents card. Every other document on either profile
 * is in a bucket (`DocumentBuckets.jsx`, GSHK 2026-11-21); identity documents
 * keep this card because each carries its own fields (number, country, dates).
 */

/**
 * One section — a heading, its documents, and its own upload button.
 *
 * RENDERED WHETHER OR NOT IT HOLDS ANYTHING. An empty section with a button is
 * how the first document gets added; before this both profiles had one button
 * in the page header for every kind of document at once, which is how a
 * passport ended up filed as an "Identity Document Scan".
 */
export function DocumentSection({ section, count, children, onAdd,
                                  canAdd = true }) {
  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">
            {section.label} <span className="count-pill">{count}</span>
          </div>
          <div className="card-sub">{section.description}</div>
        </div>
        {/* NOT RENDERED for a role that may not upload (Levi 2026-09-04). The
            SECTION still renders — an operator needs to see what is on file,
            and an empty section is itself a fact — but the button that would
            do nothing is gone. `canAdd` defaults true so a caller that has not
            been taught about permissions behaves exactly as it did. */}
        {canAdd && (
          <button className="btn btn-outline btn-sm" onClick={onAdd}>
            {section.is_identity ? 'Add Identity Document' : 'Upload Document'}
          </button>
        )}
      </div>
      {children}
    </div>
  )
}
