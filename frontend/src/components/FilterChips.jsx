import { chipsFor } from '../lib/tableFilters.js'

/**
 * Every filter currently narrowing the table, named and removable.
 *
 * This is the honest half of column filtering, and it is not decoration. Two of
 * these screens apply a filter BEFORE the operator has touched anything — the
 * dashboard opens on your own cases, the registry on the companies near their
 * anniversary — and a default that hides rows without saying so is indis-
 * tinguishable from a table that is simply missing data. A tinted header three
 * columns off-screen does not answer it either. So the chips render from first
 * paint, in one line, above the rows they explain.
 *
 * Defaults are drawn EXACTLY like a filter the operator set by hand, with the
 * same ×. There is no "Default" badge marking them as someone else's decision:
 * if it narrows the table it is a filter, and if it is a filter you can drop it.
 */
export default function FilterChips({ columns, filters, onRemove, onClearAll, extra = [] }) {
  const chips = [...extra, ...chipsFor(columns, filters)]
  if (!chips.length) return null

  return (
    <div className="fchips" aria-label="Active filters">
      <span className="fchips-lbl">Filters</span>
      {chips.map(chip => (
        <button
          key={chip.key}
          type="button"
          className="fchip"
          onClick={() => (chip.onRemove ? chip.onRemove() : onRemove(chip.cols))}
          // Named explicitly: the visible text describes the FILTER, and read
          // out on its own — "Company Name contains acme" — it gives no hint
          // that pressing it is what removes the thing being described.
          aria-label={`Remove the ${chip.label} filter`}
          title={`Remove the ${chip.label} filter`}
        >
          <span className="fchip-col">{chip.label}</span>
          {chip.text && <span className="fchip-val">{chip.text}</span>}
          <span className="fchip-x" aria-hidden="true">×</span>
        </button>
      ))}
      {chips.length > 1 && (
        <button type="button" className="fchips-clear" onClick={onClearAll}>
          Clear all
        </button>
      )}
    </div>
  )
}
