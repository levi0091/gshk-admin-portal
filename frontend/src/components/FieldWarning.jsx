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

/** The count for a card header — "3" beside the title, so an operator can see
 *  there is something to fix without opening every section. */
export function WarningCount({ count }) {
  if (!count) return null
  return (
    <span className="warn-pill" title="Fields the Companies Registry would refuse">
      {count} to fix
    </span>
  )
}
