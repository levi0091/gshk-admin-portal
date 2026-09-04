/**
 * The audit trail's two vocabularies, and how a row's subject is written.
 *
 * MODULES ARE THE SIDEBAR'S OWN NAMES. An operator asking "what happened in
 * post-incorporation this week" is naming the screen they work on, so the
 * filter offers exactly those words rather than a taxonomy invented for the
 * log. The five values must match `backend/services/audit_subject.MODULES`
 * verbatim — they go on the wire as `filter=module:in:...` and reach a closed
 * enum on the server. `auditVocabulary.test.js` and
 * `backend/tests/test_audit_subject.py` both pin the same five literals, so a
 * rename on one side fails CI instead of producing a filter option that
 * silently matches nothing.
 */

export const MODULES = [
  { value: 'post_incorporation', label: 'Post-incorporation' },
  { value: 'body_corporate', label: 'Body Corporate' },
  { value: 'natural_person', label: 'Natural Person' },
  { value: 'documents', label: 'Documents' },
  { value: 'cr_filing', label: 'CR Filing' },
]

export const MODULE_LABELS = Object.fromEntries(
  MODULES.map(m => [m.value, m.label]),
)

/** Short chips. The Subject cell is already narrow; "Body Corporate" is not. */
export const SUBJECT_KIND_LABELS = {
  case: 'Case',
  company: 'Company',
  person: 'Person',
}

/**
 * Where the Subject cell links.
 *
 * `subject_id` is the record's OWN id — a case links to its workflow screen,
 * not to its company. `case_id` (the audit column) still holds the entity id,
 * so a case row without a subject_id can still reach the company.
 */
export function subjectHref(entry) {
  if (!entry) return null
  const { subject_kind: kind, subject_id: id } = entry
  if (kind === 'person' && id) return `/persons/${id}`
  if (kind === 'case' && id) return `/cases/${id}`
  if (kind === 'company' && id) return `/companies/${id}`
  return entry.case_id ? `/companies/${entry.case_id}` : null
}

/**
 * The subject as a name and a qualifier — `{ name, ref }`, rendered "name (ref)".
 *
 * A CASE INVERTS: the case number leads and the company qualifies it, because a
 * workflow row is about one filing of one year and not about the company in
 * general. Everything else reads name-first with the identifier a human quotes
 * in brackets — a BRN for a company, an identity document for a person.
 *
 * Falls back to the raw Viewpoint key only when there is nothing else, which is
 * what the whole cell used to be.
 */
export function subjectOf(entry) {
  if (!entry) return null
  const name = entry.company_name || null
  const ref = entry.subject_ref || null

  if (entry.subject_kind === 'case') {
    // No case number yet (a case created before migration 034 backfilled one):
    // fall back to the company, rather than showing an empty lead.
    return ref ? { name: ref, ref: name } : (name ? { name, ref: null } : null)
  }
  if (name) return { name, ref }
  if (ref) return { name: ref, ref: null }
  return entry.source_keycode ? { name: entry.source_keycode, ref: null, raw: true } : null
}
