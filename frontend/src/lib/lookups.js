import { useState, useEffect } from 'react'
import { api } from './api.js'

/**
 * Reference vocabularies (gender, nationality, country, …) from the backend.
 *
 * They change when someone ships a migration, not during a session, so they are
 * fetched once per page load and shared. Without the shared promise, four forms
 * mounting at once each fired their own request for the same ~660 rows.
 */
let pending = null
let loaded = null

export function fetchLookups() {
  if (loaded) return Promise.resolve(loaded)
  if (!pending) {
    pending = api.get('/lookups')
      .then(data => { loaded = data; return data })
      .catch(err => { pending = null; throw err })
  }
  return pending
}

export function useLookups() {
  const [lookups, setLookups] = useState(loaded || {})
  useEffect(() => {
    let alive = true
    fetchLookups().then(d => { if (alive) setLookups(d) }).catch(() => {})
    return () => { alive = false }
  }, [])
  return lookups
}

/** Reset between tests. */
export function _resetLookups() {
  pending = null
  loaded = null
}

/**
 * The options to render for a field, given what is currently stored.
 *
 * Legacy Viewpoint data holds values that are not in the seeded list (a few
 * misspelled demonyms among them). Dropping them would silently blank a record
 * on the next save, so the stored value is always offered — flagged, not lost.
 */
export function optionsFor(values, current) {
  const list = Array.isArray(values) ? values : []
  if (!current || list.some(v => v.code === current)) return list
  return [...list, { code: current, label: `${current} (not in list)` }]
}
