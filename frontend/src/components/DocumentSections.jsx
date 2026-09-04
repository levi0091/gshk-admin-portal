import { formatDateTime } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'

//: How many type colours exist. Must match the `.doc-type-c0..c7` rules in
//: index.css — a hash landing outside them would render an unstyled chip.
const TYPE_COLOURS = 8

/**
 * A stable colour index for a document type (Levi 2026-09-04: "maybe a
 * different document type a different colour").
 *
 * Deterministic on the CODE, not on position in the list: a type must keep its
 * colour when another type is uploaded above it, or the colour is telling you
 * about the sort order rather than about the document.
 *
 * COLOUR IS REINFORCEMENT, NEVER THE MESSAGE. Every chip also spells the type
 * out and CURRENT / SUPERSEDED is a separate tag with its own words, so nothing
 * here requires telling two hues apart. That is also why the eight are kept off
 * `--carrot` (needs attention) and `--bang` (approved): a document type that
 * happened to hash onto one of those would be claiming a status it has not got.
 */
export function typeColour(code) {
  let hash = 0
  for (const ch of String(code || '')) hash = (hash * 31 + ch.charCodeAt(0)) % 100000
  return hash % TYPE_COLOURS
}

/** What the document IS, set loud and in its own colour. */
export function TypeChip({ doc }) {
  return (
    <span className={`doc-type-chip doc-type-c${typeColour(doc.document_type_code)}`}>
      {doc.document_types?.label || doc.document_type_code}
    </span>
  )
}

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
export function DocumentSection({ section, count, children, onAdd,
                                  canAdd = true, addReason }) {
  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">
            {section.label} <span className="count-pill">{count}</span>
          </div>
          <div className="card-sub">{section.description}</div>
        </div>
        {/* DISABLED RATHER THAN REMOVED for a role that may only read. The
            section still has to render — an operator needs to see what is on
            file — and a button that vanishes makes the screen look like a
            different, smaller product rather than the same one with less
            granted. `canAdd` defaults true so a caller that has not been
            taught about permissions behaves exactly as it did. */}
        <button className="btn btn-outline btn-sm" onClick={onAdd}
                disabled={!canAdd} title={canAdd ? undefined : addReason}>
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
export function SectionDocuments({ documents, busy, onRemove,
                                   canDownload = true, downloadReason,
                                   canRemove = true, removeReason }) {
  return documents.map(doc => (
    <div className="sec-doc" key={doc.id}>
      <div className="sec-doc-l">
        <div className="sec-doc-type">
          <TypeChip doc={doc} />
        </div>
        <div className="sec-doc-sub">
          {[doc.title, doc.file_name,
            doc.current_version > 1 && `v${doc.current_version}`,
            formatDateTime(doc.updated_at || doc.created_at)]
            .filter(Boolean).join(' · ')}
        </div>
      </div>
      <div className="sec-doc-actions">
        {/* Download is `documents:read` and Remove is `documents:delete` —
            two different permissions, so they disable independently. A role
            that may read the file but not destroy it is the common case. */}
        <button className="dv-dl" onClick={() => downloadDocument(doc.id)}
                disabled={!canDownload}
                title={canDownload ? undefined : downloadReason}>
          Download
        </button>
        <button className="dv-dl dv-rm" onClick={() => onRemove(doc)}
                disabled={busy || !canRemove}
                title={canRemove ? undefined : removeReason}>
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
export function DocumentHistory({ documents, sectionLabels,
                                  canDownload = true, downloadReason }) {
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
          {/* The type is what someone scanning this list is looking for, so it
              is the loud element — same chip, same colour, as the section
              above, so one document reads the same in both places. */}
          <TypeChip doc={doc} />
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
                // THE VERSION, not the document. Every button in this list used
                // to sign the CURRENT version's path, so v1 and v2 both handed
                // back v3 under three different file names — the older bytes
                // were in `document_versions.storage_path` the whole time and
                // nothing read them.
                <button className="dv-dl"
                        onClick={() => downloadDocument(doc.id, latest ? null : v.version_number)}
                        disabled={!canDownload}
                        title={canDownload ? undefined : downloadReason}>
                  Download
                </button>
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
