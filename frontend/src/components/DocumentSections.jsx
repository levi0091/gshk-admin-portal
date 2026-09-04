import { formatDateTime } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'

/**
 * The document sections shared by the person and company profiles.
 *
 * Both screens file uploads the same way — by `document_types.category`, one
 * card per section, the versions in a single history below (migration 036) —
 * so they share the components rather than each growing their own copy. What
 * differs between them is what else the section holds: a person's Identity
 * Documents card renders identity RECORDS, which the company has none of.
 */

/**
 * One section — a heading, its documents, and its own upload button.
 *
 * RENDERED WHETHER OR NOT IT HOLDS ANYTHING. An empty section with a button is
 * how the first document gets added; before this both profiles had one button
 * in the page header for every kind of document at once, which is how a
 * passport ended up filed as an "Identity Document Scan".
 */
export function DocumentSection({ section, count, children, onAdd }) {
  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">
            {section.label} <span className="count-pill">{count}</span>
          </div>
          <div className="card-sub">{section.description}</div>
        </div>
        <button className="btn btn-outline btn-sm" onClick={onAdd}>
          {section.is_identity ? 'Add Identity Document' : 'Upload Document'}
        </button>
      </div>
      {children}
    </div>
  )
}

/**
 * The current file held under each type in one section.
 *
 * Download and Remove live HERE, beside the document, and not only down in
 * Document History (Levi 2026-09-04). The section is where an operator looks
 * for what is on file; the history is where they look for what happened to it.
 */
export function SectionDocuments({ documents, busy, onRemove }) {
  return documents.map(doc => (
    <div className="sec-doc" key={doc.id}>
      <div className="sec-doc-l">
        <div className="sec-doc-type">
          {doc.document_types?.label || doc.document_type_code}
        </div>
        <div className="sec-doc-sub">
          {[doc.title, doc.file_name,
            doc.current_version > 1 && `v${doc.current_version}`,
            formatDateTime(doc.updated_at || doc.created_at)]
            .filter(Boolean).join(' · ')}
        </div>
      </div>
      <div className="sec-doc-actions">
        <button className="dv-dl" onClick={() => downloadDocument(doc.id)}>Download</button>
        <button className="dv-dl dv-rm" onClick={() => onRemove(doc)} disabled={busy}>
          Remove
        </button>
      </div>
    </div>
  ))
}

/**
 * Every upload, grouped by type, newest version current.
 *
 * Each group names its SECTION as well as its type — "Passport" alone does not
 * say whether it was filed as identity or as proof of address, and the two live
 * in different sections. The timestamp is the upload's own datetime, in Hong
 * Kong, because two uploads on one day are otherwise indistinguishable.
 *
 * REMOVED DOCUMENTS APPEAR HERE AND NOWHERE ELSE. That is the whole point of a
 * soft delete: the file leaves the section it was filed under, and the record
 * that it once existed does not leave at all.
 */
export function DocumentHistory({ documents, sectionLabels }) {
  if (!documents?.length) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No documents uploaded yet.</div>
  }
  return documents.map(doc => {
    const versions = [...(doc.document_versions || [])]
      .sort((a, b) => b.version_number - a.version_number)
    const section = sectionLabels?.[doc.document_types?.category]
    const removed = doc.status === 'deleted'
    return (
      <div key={doc.id} className={removed ? 'doc-hist-removed' : undefined}>
        <div className="doc-hist-type">
          {section && <span className="doc-hist-cat">{section}</span>}
          {doc.document_types?.label || doc.document_type_code}
          {removed && <span className="dv-tag dv-rmv">REMOVED</span>}
          <span className="cnt">{versions.length} version{versions.length === 1 ? '' : 's'}</span>
        </div>
        {versions.map(v => {
          // Three states, not two. A removed document has no CURRENT version —
          // calling its newest file current would contradict the section it no
          // longer appears in — but neither was that file SUPERSEDED, which
          // means a later upload replaced it. The one that was live when the
          // document was removed says so; the ones before it were superseded
          // exactly as they always were.
          const latest = v.version_number === doc.current_version
          const state = removed && latest ? 'removed' : latest ? 'current' : 'superseded'
          return (
            <div className="doc-ver" key={v.id}>
              <span className="dv-l">
                <span className={`dv-tag dv-${state}`}>{state.toUpperCase()}</span>
                <span>v{v.version_number} · {v.file_name}</span>
                <span className="dv-meta">{formatDateTime(v.created_at)}</span>
              </span>
              {/* A removed document is not downloadable — `create_signed_url`
                  404s a deleted one, so offering the button would be a lie. */}
              {!removed && (
                <button className="dv-dl" onClick={() => downloadDocument(doc.id)}>Download</button>
              )}
            </div>
          )
        })}
      </div>
    )
  })
}

/**
 * "Removing X" — the dialog body both profiles show for an uploaded file.
 *
 * The copy is here rather than in each page because the promise it makes is the
 * service's, not the screen's: `soft_delete_document` retains the object and
 * every version row, and only flips `status`.
 */
export function RemoveDocumentBody({ doc }) {
  return (
    <>
      <p>
        Removing <b>{doc.document_types?.label || doc.document_type_code}</b>
        {doc.file_name ? ` (${doc.file_name})` : ''}.
      </p>
      <p className="confirm-note">
        It leaves this section and stays in Document History, marked removed.
        Every version is retained.
      </p>
    </>
  )
}
