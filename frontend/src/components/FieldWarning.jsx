/**
 * What CR would say about this value, said here instead.
 *
 * PRD §5.3. The alternative is what used to happen: an over-long address line
 * or an empty country reaches `nar1.validate` weeks after it was typed, comes
 * back as a `ValueError`, and reads as a crash in the filing screen rather
 * than as a field somebody needs to fix.
 *
 * Deliberately NOT an error style. Nothing here blocks the save — the record
 * is allowed to be incomplete, because most of these came out of Viewpoint
 * that way and refusing to store them would just mean refusing to show them.
 * The blocking set is much smaller and lives on the Open case button.
 */
export default function FieldWarning({ warning }) {
  if (!warning) return null
  return (
    <span className={`fld-warn fld-warn-${warning.kind}`} role="note">
      {warning.message}
    </span>
  )
}

/**
 * The count for a card header, so an operator can see there is something to fix
 * without opening every section.
 *
 * IT READS "1 Missing Information", IN RED (Levi 2026-09-07). It used to read
 * "1 to fix" in the same carrot as the field notes below it, which made the
 * summary as quiet as the detail it was summarising — an operator scanning a
 * profile went past it. This is the one mark on the card that has to survive
 * being glanced at, so it is the one place the red is spent; the per-field
 * `.fld-warn` notes stay carrot, because each of those is a single incomplete
 * value and the save is still allowed to proceed.
 *
 * The wording is deliberately not pluralised. Levi asked for this string, and
 * a header that reads "1 Missing Information" then "2 Missing Information" is
 * one label with a number in front of it — which is what an operator is
 * scanning for. The `title` still says what the count actually covers, because
 * a value that is present but too long for CR is counted here too.
 */
export function WarningCount({ count }) {
  if (!count) return null
  return (
    <span className="warn-pill"
          title="Fields the Companies Registry would refuse — missing, or too long">
      {count} Missing Information
    </span>
  )
}
