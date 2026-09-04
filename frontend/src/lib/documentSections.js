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
    identity_fields: (data && typeof data.identity_fields === 'object'
      && data.identity_fields) || {},
  }
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
      : { sections: [], identity_fields: {}, ready: false, error: '' }
  })
  useEffect(() => {
    let alive = true
    fetchDocumentSections(ownerType)
      .then(d => { if (alive) setState({ ...d, ready: true, error: '' }) })
      .catch(err => {
        if (alive) {
          setState({
            sections: [], identity_fields: {}, ready: true,
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
 * Documents grouped under the section their type belongs to.
 *
 * Keyed on the EMBEDDED `document_types.category`, so a document uploaded under
 * a since-retired type (`id_scan`, the old catch-all) still lands in the right
 * section instead of disappearing from the screen. Anything whose category
 * matches no section falls to the last one, which is deliberately "Other
 * Documents" — a document rendered under the wrong heading is recoverable, one
 * rendered nowhere is not.
 */
export function groupBySection(documents, sections) {
  const keys = (Array.isArray(sections) ? sections : []).map(s => s.key)
  const fallback = keys[keys.length - 1]
  const grouped = Object.fromEntries(keys.map(k => [k, []]))
  for (const doc of documents || []) {
    const category = doc.document_types?.category
    const key = keys.includes(category) ? category : fallback
    if (grouped[key]) grouped[key].push(doc)
  }
  return grouped
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
