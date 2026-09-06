import { splitProblem, splitLocator, splitFieldPath } from '../../lib/problemText.js'
import { readFault } from './FaultPanel.jsx'

/**
 * The evidence under a workflow refusal — one card per thing that is wrong.
 *
 * THE QUESTION THIS SCREEN ANSWERS. When the pre-submit gate stops a filing,
 * the operator is not asking "what is the field called". They have the company
 * profile open in another tab and they are asking ONE thing: which of these two
 * records is right? So the two VALUES are the largest type in the card and the
 * field name is a quiet eyebrow above them — the inverse of the table this
 * replaced, which led with the field name and made the values the third column
 * you read.
 *
 * The arrow between the panes is doing work: it says the form BECAME the
 * profile, which is the direction of the change. Three table columns cannot
 * say that; they only sit next to each other.
 *
 * Cards are white inside a red shell on purpose. The shell has already said
 * "stopped"; the cards are evidence, and someone has to read a Swedish street
 * address off one of them. Tinting evidence with alarm makes it harder to read
 * and says nothing the shell has not said already.
 *
 * They are NOT numbered. Numbering implies a sequence, and these are a set —
 * every one has to be dealt with and no order is implied.
 */

/** CR's severity words. Not places on the record — see ProblemCard. */
const SEVERITIES = new Set(['ERROR', 'ERR', 'WARNING', 'WARN', 'FATAL', 'INFO'])

/**
 * A filed particular that moved between approval and now (`differences`).
 *
 * `validated` / `current` are null when the field is ABSENT from that version
 * — a director who joined or left the board, not a field someone blanked. That
 * distinction is load-bearing, so it is rendered as words rather than as an
 * empty cell that would read "unchanged, empty".
 */
export function MismatchCard({ difference }) {
  const { path, field } = splitFieldPath(difference.field)
  return (
    <li className="rf-card" data-testid="mismatch-card">
      <div className="rf-where">
        {path.map((p, i) => (
          <span key={i} className="rf-where-step">{p}</span>
        ))}
        <span className="rf-where-field">{field || difference.path}</span>
      </div>

      <div className="rf-compare">
        <div className="rf-val">
          <div className="rf-val-lbl">On the NAR1 the client approved</div>
          <div className="rf-val-txt">
            {difference.validated ?? <span className="rf-absent">Not on the form</span>}
          </div>
        </div>
        {/* Rotates to point down when the panes stack. Hidden from screen
            readers: the two labels already say which is which, and "right
            arrow" between them adds nothing a reader can use. */}
        <div className="rf-arrow" aria-hidden="true">→</div>
        <div className="rf-val rf-val-now">
          <div className="rf-val-lbl">In the company profile now</div>
          <div className="rf-val-txt">
            {difference.current ?? <span className="rf-absent">No longer on record</span>}
          </div>
        </div>
      </div>
    </li>
  )
}

/**
 * A fault with no pair to compare — the record cannot produce a return at all,
 * so there is no "before" value, only a value CR will not take.
 *
 * Same rail and same eyebrow as the mismatch card, so a screen showing both
 * reads as one list of faults rather than two unrelated widgets.
 */
export function ProblemCard({ problem }) {
  // CR sends (code, message) PAIRS; our own faults are plain strings. readFault
  // normalises both, and skipping it is how ["ERR_MSG_...","..."] reached the
  // screen as JSON once already.
  const { field, msg } = readFault(problem)
  const { locator, headline, detail } = splitProblem(msg)
  // For a CR fault, readFault's `field` is the SEVERITY ("ERROR"), not a
  // place on the record. An eyebrow reading "ERROR" above a card already
  // inside a refusal says nothing and looks like a locator, so severities are
  // dropped and anything else is kept.
  const named = field && !SEVERITIES.has(String(field).toUpperCase()) ? field : null
  const where = splitLocator(locator) || (named ? { kind: null, name: named } : null)

  return (
    <li className="rf-card" data-testid="problem-card">
      {where && (
        <div className="rf-where">
          {/* The kind is only context when there is a NAME after it. "entity"
              resolves to a kind and no name, and rendering it in both slots
              produced the eyebrow "THIS COMPANY · THIS COMPANY". */}
          {where.kind && where.name && (
            <span className="rf-where-step">{where.kind}</span>
          )}
          <span className="rf-where-field">{where.name || where.kind}</span>
        </div>
      )}
      <div className="rf-problem">{headline}</div>
      {detail && <div className="rf-detail">{detail}</div>}
    </li>
  )
}

/**
 * The evidence list for whichever kind of refusal this is.
 *
 * `differences` and `problems` are never both present in practice, but both are
 * rendered if they are — dropping one silently is how an operator fixes half a
 * problem and presses Submit again.
 */
export default function RefusalDetail({ differences, problems }) {
  const hasDiff = Array.isArray(differences) && differences.length > 0
  const hasProblems = Array.isArray(problems) && problems.length > 0
  if (!hasDiff && !hasProblems) return null

  return (
    <ul className="rf-list" data-testid="refusal-detail">
      {hasDiff && differences.map(d => (
        <MismatchCard key={d.path || d.field} difference={d} />
      ))}
      {hasProblems && problems.map((p, i) => (
        <ProblemCard key={i} problem={p} />
      ))}
    </ul>
  )
}
