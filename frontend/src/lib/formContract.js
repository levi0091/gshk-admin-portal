import { useState, useEffect } from 'react'
import { api } from './api.js'

/**
 * What the Companies Registry requires of each profile field.
 *
 * WHY THIS EXISTS. The profile forms carried their own idea of which fields
 * matter and how long they may be, and CR's idea lived in `nar1_mapper`. The
 * two could disagree with nothing noticing, and the way you found out was a
 * rejected filing: an over-long address line arrives as a `ValueError` out of
 * `nar1.validate` weeks after someone typed it, and reads as a crash.
 *
 * `GET /form-contract` is generated from CR's own worksheet, so this is the
 * same answer the API enforces on write — read backwards, to warn before the
 * save rather than refuse after it.
 *
 * Shape: `table -> column -> { max_length, mandatory, cr_fields }`.
 */
let pending = null
let loaded = null

export function fetchFormContract() {
  if (loaded) return Promise.resolve(loaded)
  if (!pending) {
    pending = api.get('/form-contract')
      .then(data => { loaded = data || {}; return loaded })
      // Highlighting is an aid, not a precondition: a profile must still
      // render for a role that cannot read the contract. An empty contract
      // warns about nothing, which is the correct failure direction.
      .catch(() => { loaded = {}; return loaded })
  }
  return pending
}

export function useFormContract() {
  const [contract, setContract] = useState(loaded || {})
  useEffect(() => {
    let alive = true
    fetchFormContract().then(c => { if (alive) setContract(c) })
    return () => { alive = false }
  }, [])
  return contract
}

/** Reset between tests. */
export function _resetFormContract() {
  pending = null
  loaded = null
}

/**
 * What is wrong with one value, as CR would see it — or null.
 *
 * Only two things can be wrong here, and both are things CR itself refuses:
 * a field it requires that nobody filled in, and a value longer than it
 * accepts. A column the contract has no entry for is never flagged: those are
 * the `unsourced` fields, and the portal is not going to nag about data it
 * decided not to hold.
 */
export function fieldWarning(contract, table, column, value) {
  const rule = contract?.[table]?.[column]
  if (!rule) return null

  // A number is not empty because it is 0, and 0 shares paid up is an answer.
  const text = value == null ? '' : String(value)
  if (!text.trim()) {
    if (!rule.mandatory) return null
    return {
      kind: 'missing',
      message: 'The Companies Registry requires this on the return.',
    }
  }

  // Measured in the characters CR receives, which is why a number is
  // stringified first — `issuedCapital` is capped at 16 characters, not at a
  // magnitude.
  if (rule.max_length && text.length > rule.max_length) {
    return {
      kind: 'too_long',
      message: `${text.length} characters — the Companies Registry accepts `
        + `${rule.max_length}.`,
    }
  }
  return null
}

/**
 * Every problem on one record, keyed by column, so a card header can show a
 * single count and each field can show its own reason.
 *
 * Only columns the record actually carries are considered. A list row selects
 * a handful of columns, and treating absent-from-the-payload as
 * empty-in-the-database would turn a narrow SELECT into a screen full of
 * warnings that are not true.
 */
export function warningsFor(contract, table, record) {
  const rules = contract?.[table]
  if (!rules || !record) return {}

  const out = {}
  for (const column of Object.keys(rules)) {
    if (!(column in record)) continue
    const warning = fieldWarning(contract, table, column, record[column])
    if (warning) out[column] = warning
  }
  return out
}
