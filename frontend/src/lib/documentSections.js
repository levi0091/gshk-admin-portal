import { useState, useEffect } from 'react'
import { api } from './api.js'

/**
 * The document sections a profile renders, from the server that enforces them.
 *
 * READ, NEVER HARDCODED — the same rule `formContract.js` follows. The API
 * decides that a passport needs an issuing country (CR refuses the number
 * without one) and that an identity document may be recorded without a scan.
 * A screen carrying its own copy of those rules drifts from the one doing the
 * refusing, and the way that surfaces is a save rejected for a reason the form
 * never mentioned.
 *
 * Shaped like the lookups cache below it: sections change when someone ships a
 * migration, not during a session.
 */
const cache = new Map()
const pending = new Map()

/**
 * Whatever came back, in the shape the screens index into.
 *
 * The profile decides what to render from `sections`, so a payload without one
 * has to become an empty list here rather than an undefined further in. A
 * `.map` of undefined three components deep reports itself as a blank page.
 */
function normalise(data) {
  return {
    sections: Array.isArray(data?.sections) ? data.sections : [],
    buckets: Array.isArray(data?.buckets) ? data.buckets : [],
    upload_limits: { ...DEFAULT_LIMITS, ...(data?.upload_limits || {}) },
    identity_fields: (data && typeof data.identity_fields === 'object'
      && data.identity_fields) || {},
  }
}

/**
 * The API's numbers, used only until `/documents/sections` answers. The API
 * refuses the same things again, so a stale copy here can only make the screen
 * stricter or looser than the server for a moment, never wrong in the record.
 */
export const DEFAULT_LIMITS = {
  max_files: 20,
  max_file_bytes: 50 * 1024 * 1024,
  blocked_extensions: [],
  max_tags: 12,
  max_tag_length: 60,
  max_description_length: 500,
}

export function fetchDocumentSections(ownerType = 'person') {
  if (cache.has(ownerType)) return Promise.resolve(cache.get(ownerType))
  if (!pending.has(ownerType)) {
    pending.set(
      ownerType,
      api.get(`/documents/sections?owner_type=${ownerType}`)
        .then(data => {
          const value = normalise(data)
          cache.set(ownerType, value)
          return value
        })
        .catch(err => { pending.delete(ownerType); throw err }),
    )
  }
  return pending.get(ownerType)
}

/**
 * `{ sections, identity_fields, ready, error }`.
 *
 * `ready` and `error` exist because the sections decide what the profile shows.
 * An empty list is indistinguishable from a failed fetch, and a screen that
 * treats the two the same silently renders a director as holding NO identity
 * documents because a lookup call timed out. The caller has to be able to say
 * "unavailable" rather than "none".
 */
export function useDocumentSections(ownerType = 'person') {
  const [state, setState] = useState(() => {
    const hit = cache.get(ownerType)
    return hit ? { ...hit, ready: true, error: '' }
      : { ...normalise(null), ready: false, error: '' }
  })
  useEffect(() => {
    let alive = true
    fetchDocumentSections(ownerType)
      .then(d => { if (alive) setState({ ...d, ready: true, error: '' }) })
      .catch(err => {
        if (alive) {
          setState({
            ...normalise(null), ready: true,
            error: err?.message || 'Could not load the document sections',
          })
        }
      })
    return () => { alive = false }
  }, [ownerType])
  return state
}

/** Reset between tests. */
export function _resetDocumentSections() {
  cache.clear()
  pending.clear()
}

/**
 * Live documents grouped by the bucket the API placed them in, newest upload
 * first (GSHK 2026-11-21: "the buckets will be sorted based on uploaded date").
 *
 * The API decides the bucket (`document_sections.bucket_of`): a chosen one, or
 * one derived from a legacy type. A document whose bucket the screen does not
 * know falls into the fallback rather than vanishing; one with NO bucket is a
 * person's identity scan, which renders on its identity record instead.
 */
export function groupByBucket(documents, buckets) {
  const list = Array.isArray(buckets) ? buckets : []
  const keys = list.map(b => b.key)
  const fallback = (list.find(b => b.fallback) || list[list.length - 1])?.key
  const grouped = Object.fromEntries(keys.map(k => [k, []]))
  for (const doc of documents || []) {
    if (doc.status === 'deleted' || !doc.bucket) continue
    const key = keys.includes(doc.bucket) ? doc.bucket : fallback
    if (grouped[key]) grouped[key].push(doc)
  }
  for (const k of keys) {
    grouped[k].sort((a, b) =>
      String(b.uploaded_at || b.created_at || '').localeCompare(
        String(a.uploaded_at || a.created_at || '')))
  }
  return grouped
}

/** "report.final.PDF" -> "pdf"; no dot -> "". */
export function extensionOf(name) {
  const n = String(name || '').trim().toLowerCase()
  const i = n.lastIndexOf('.')
  return i > 0 && i < n.length - 1 ? n.slice(i + 1) : ''
}

/**
 * Why the screen will not send this file, or ''. The same three refusals the
 * API makes (`document_sections.upload_refusal`), so the operator hears about
 * a 60 MB scan before it has crossed the wire rather than after.
 */
export function refusalFor(file, limits = DEFAULT_LIMITS) {
  const size = Number(file?.size || 0)
  if (size <= 0) return 'The file is empty'
  if (size > limits.max_file_bytes) {
    return `Larger than ${Math.round(limits.max_file_bytes / (1024 * 1024))} MB`
  }
  const ext = extensionOf(file?.name)
  if (ext && (limits.blocked_extensions || []).includes(ext)) {
    return `.${ext} files can run code when opened, so they cannot be stored here`
  }
  return ''
}

/** The identity-document field rules for one `id_type`. */
export function identityRules(identityFields, idType) {
  return identityFields?.[idType] || { fields: [], required: [] }
}

/**
 * How each identity field is rendered — one descriptor, used by the card that
 * shows it, the card that edits it and the modal that creates it.
 *
 * `issuing_country` draws on `cr_country` and NOT `lookup_values.country`.
 * Viewpoint's list holds 20 codes CR cannot resolve; one of them ('HK-CH', the
 * Chinese "Hong Kong") reached a real case and killed the return at Data
 * Verification.
 *
 * There is no Renewal Reminder. It was on this card and nobody asked for it
 * (Levi, 2026-09-04); the column survives, the field does not.
 */
export const IDENTITY_FIELD = {
  id_number: { key: 'id_number', label: 'ID Number' },
  issuing_country: {
    key: 'issuing_country', label: 'Issuing Country/Region', lookup: 'cr_country',
  },
  issue_date: { key: 'issue_date', label: 'Issue Date', type: 'date' },
  expiry_date: { key: 'expiry_date', label: 'Expiry Date', type: 'date' },
}

/**
 * The fields to render for one stored identity document.
 *
 * The type's own fields, plus any field OUTSIDE them that already holds a
 * value. An HKID has no issuing country as far as CR is concerned — there is no
 * country box beside `<hkid>` — but Viewpoint rows carry one, and a screen that
 * hid it would be quietly dropping data the operator can still see in the
 * source system.
 */
export function fieldsForStoredDocument(identityFields, doc) {
  const allowed = identityRules(identityFields, doc?.id_type).fields || []
  const extra = Object.keys(IDENTITY_FIELD).filter(
    k => !allowed.includes(k) && doc?.[k])
  return [...allowed, ...extra].map(k => IDENTITY_FIELD[k]).filter(Boolean)
}
