/**
 * Turning one backend fault string into the three parts a card renders.
 *
 * WHY THIS EXISTS. The NAR1 mapper writes every fault as
 *
 *     "<locator>: <what is wrong> — <why, and what to do about it>"
 *
 * which is a good sentence and an unreadable line. On screen it arrived as a
 * single wrapped paragraph carrying a company name, a country code, a CR
 * worksheet version and an instruction, drawn above the Submit button:
 *
 *   "the company record can no longer be mapped to a NAR1: corporate party
 *    CGAHCHBAABBG DIRECTOR COMPANY LIMITED: no CR region code is known for
 *    country 'HK-CH' — CR's Country & Region sheet (worksheet v1.0.14)
 *    carries no code, alpha-2 or English name matching it; correct the
 *    address rather than guessing a code CR would take the fee for and then
 *    reject"
 *
 * Every fact in there is one the operator needs. The problem is that they
 * arrive in one breath, so the eye has nowhere to land (Levi, 2026-09-03).
 *
 * This is PRESENTATION, deliberately kept out of the backend. The fault text
 * is written for a person and the split is a reading aid — pushing it into the
 * API would freeze a wording choice into a contract, and any fault that did
 * not match the shape would then have to be invented into it. Here, a fault
 * that does not split simply renders whole, which is what it did before.
 */

/**
 * The locator nouns the mapper actually writes, longest first so
 * "corporate party" wins over "corporate".
 *
 * Mirrors the `where` strings in `services/tpsi/forms/nar1_mapper.py`. A
 * locator outside this list still renders — it just keeps its own words rather
 * than being split into kind and name.
 */
const LOCATORS = [
  ['corporate party', 'Corporate party'],
  ['share class', 'Share class'],
  ['shareholding', 'Shareholding'],
  ['shareholder', 'Shareholder'],
  ['signatory', 'Signatory'],
  ['officer', 'Officer'],
  ['person', 'Person'],
  ['entity', 'This company'],
]

/** Sentence punctuation. A "locator" containing any of it is a sentence that
 *  happened to have a colon in it, not a locator. */
const SENTENCE = /[.!?]/

/**
 * Split `"corporate party ACME LIMITED"` into a kind and a name.
 *
 * The NAME is what the operator types into the profile search, so it is the
 * half that gets emphasis; the kind only says which register to look in.
 */
export function splitLocator(locator) {
  const text = String(locator || '').trim()
  if (!text) return null
  for (const [prefix, kind] of LOCATORS) {
    if (text === prefix) return { kind, name: null }
    if (text.toLowerCase().startsWith(`${prefix} `)) {
      return { kind, name: text.slice(prefix.length + 1).trim() || null }
    }
  }
  return { kind: null, name: text }
}

/**
 * `"corporate party ACME: no code for 'HK-CH' — CR's sheet carries none"`
 * becomes `{ locator, headline, detail }`.
 *
 * Nothing is ever dropped: a string that matches none of the shapes comes back
 * as `{ locator: null, headline: <the whole string>, detail: null }`.
 */
export function splitProblem(problem) {
  const text = typeof problem === 'string'
    ? problem.trim()
    : String(problem ?? '').trim()
  if (!text) return { locator: null, headline: '', detail: null }

  let locator = null
  let rest = text

  // The FIRST ": ", and only when what precedes it reads like a locator:
  // short, and with no sentence punctuation in it. Without both guards a
  // fault whose explanation contains a colon would lose its first clause to
  // the eyebrow.
  const colon = text.indexOf(': ')
  if (colon > 0 && colon <= 80) {
    const head = text.slice(0, colon)
    if (!SENTENCE.test(head)) {
      locator = head
      rest = text.slice(colon + 2).trim()
    }
  }

  // The em dash separates the fault from its explanation. The mapper writes
  // it consistently; a fault without one is all headline, which is correct —
  // those are the short ones ("no address on record").
  let headline = rest
  let detail = null
  const dash = rest.indexOf(' — ')
  if (dash > 0) {
    headline = rest.slice(0, dash).trim()
    detail = rest.slice(dash + 3).trim()
  }

  return {
    locator,
    headline: sentence(headline),
    detail: detail ? sentence(detail) : null,
  }
}

/**
 * Capitalise, and close with a full stop.
 *
 * The fault text is written as a clause following a colon, so it starts
 * lower-case and ends bare. Standing alone in a card it is a sentence and
 * should look like one — but a fragment that starts with a quoted value or a
 * code is left exactly as written, because upper-casing `'HK-CH'` or `brNo`
 * would misreport what is on the record.
 */
function sentence(text) {
  if (!text) return text
  const first = text[0]
  const capitalised = /[a-z]/.test(first) ? first.toUpperCase() + text.slice(1) : text
  return /[.!?;,]$/.test(capitalised) ? capitalised : `${capitalised}.`
}

/**
 * The trailing segment of a drift path label — the field itself.
 *
 * `_label()` in `services/tpsi/drift.py` builds
 * "Director (individual) 2 · Address · Building": a route through the form
 * ending at the field. The route is context and the field is the subject, so
 * they are rendered with different weight rather than as one grey string.
 */
export function splitFieldPath(label) {
  const parts = String(label || '').split(' · ').map(s => s.trim()).filter(Boolean)
  if (!parts.length) return { path: [], field: '' }
  return { path: parts.slice(0, -1), field: parts[parts.length - 1] }
}
