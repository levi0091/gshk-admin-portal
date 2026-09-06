/**
 * What a listing says when it has nothing to show.
 *
 * Levi 2026-09-04, after filtering the dashboard down to nothing: "it should not
 * say 'Failed to load cases. Failed to fetch', it should say 'No records
 * found'". The literal cause of that message was a 500 (a uuid column filtered
 * with `ilike`, fixed in `table_filters`), but the point survives the bug: an
 * empty table and a broken request are different facts, and only one of them is
 * the operator's to act on.
 *
 * So this row states the fact plainly and then, ONLY when a filter is
 * responsible, offers the one action that changes it. Without that second half
 * the message is a dead end on a screen that filters itself on first paint —
 * "no records" reads as "there is no data" rather than "you are looking through
 * a filter", and the two are very different things to be told about a register
 * of 5,930 companies.
 */
export default function EmptyRow({ filtered, onClear }) {
  return (
    <div className="empty-row">
      {/* Levi's words, and the same three on all three listings — a register
          that greets you differently on each screen is one more thing to
          learn for nothing. */}
      <div className="empty-row-hd">No records found</div>
      {filtered && (
        <>
          <div className="empty-row-sub">
            Every row is filtered out. Adjust a column filter, or start again.
          </div>
          <button type="button" className="btn btn-outline btn-sm" onClick={onClear}>
            Clear all filters
          </button>
        </>
      )}
    </div>
  )
}
