import { optionsFor } from '../lib/lookups.js'

/**
 * One address, in the five fields the Companies Registry actually receives.
 *
 * WHY THIS COMPONENT EXISTS. Both profiles showed an address as one
 * comma-joined string and neither could edit it — the company form dropped it
 * from edit mode entirely, and no endpoint existed to change an address row's
 * text. A NAR1 carries every director's residential address, so 815 of 6,853
 * people had an address CR would refuse and nowhere to fix it.
 *
 * The joined string is also how the damage stayed invisible: an address that
 * files and one that CR refuses read identically once the lines are joined.
 *
 * WHY THE FIELDS ARE SPLIT THIS WAY. They map one-to-one onto CR's nodes, and
 * that mapping is the whole point — a single free-text box is what let the data
 * go wrong. `nar1_mapper._address` is the other half of this contract:
 *
 *     line1  -> flatFlrBlk         Flat / Floor / Block
 *     line2  -> bldg               Building
 *     line3  -> stEstLotVlg        Street / Estate / Lot / Village
 *     city   -> dstCtyStatePostal  District
 *     country-> ctryRegion         Country
 *
 * THE COUNTER IS NOT DECORATION. CR caps each line at 60 characters and
 * refuses the whole filing over one long line. Showing the count where the
 * typing happens is what stops the data going bad a second time; the API
 * refuses it too, but by then the operator has lost their work.
 */

/** CR's per-line cap. Mirrors `nar1_schema.json` and `address_service.LIMIT`. */
export const LIMIT = 60

const LINES = [
  ['line1', 'Flat / Floor / Block'],
  ['line2', 'Building'],
  ['line3', 'Street / Estate / Lot / Village'],
]

const HK = 'HK'

export default function AddressBlock({ value, lookups, onChange, readOnly = false }) {
  const a = value || {}
  const isHK = (a.country || '').toUpperCase() === HK
  const sharedBy = Number(a.shared_by || 0)

  if (readOnly) {
    return (
      <div className="addr-block" data-testid="address-block">
        {LINES.map(([key, label]) => (
          <div className="kv-row" key={key}>
            <span className="kv-key">{label}</span>
            <span className="kv-val">{a[key] || <span className="td-muted">—</span>}</span>
          </div>
        ))}
        <div className="kv-row">
          <span className="kv-key">District</span>
          <span className="kv-val">{a.city || <span className="td-muted">—</span>}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">Country</span>
          <span className="kv-val">{a.country || <span className="td-muted">—</span>}</span>
        </div>
        <SharedNote count={sharedBy} readOnly />
      </div>
    )
  }

  return (
    <div className="addr-block" data-testid="address-block">
      {LINES.map(([key, label]) => (
        <CountedLine
          key={key}
          id={key}
          label={label}
          value={a[key] || ''}
          onChange={next => onChange(key, next)}
        />
      ))}

      <div className="f-group">
        <label className="f-label" htmlFor="addr_city">District</label>
        {isHK ? (
          // For a Hong Kong address CR reads District as a CONTROLLED CODE,
          // not free text: "WAN CHAI" was refused live while "WANCHAI" passed.
          // A dropdown of CR's own 125 codes cannot produce that mistake.
          <select
            id="addr_city"
            className="f-select"
            value={a.city || ''}
            onChange={e => onChange('city', e.target.value)}
          >
            <option value="">Select…</option>
            {optionsFor(lookups?.cr_district, a.city).map(o => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
        ) : (
          <input
            id="addr_city"
            className="f-input"
            value={a.city || ''}
            onChange={e => onChange('city', e.target.value)}
          />
        )}
        <span className="f-hint">
          {isHK
            ? 'One of the Companies Registry’s district codes.'
            : 'City, region or postcode — free text outside Hong Kong.'}
        </span>
      </div>

      <div className="f-group">
        <label className="f-label" htmlFor="addr_country">Country</label>
        <select
          id="addr_country"
          className="f-select"
          value={a.country || ''}
          onChange={e => onChange('country', e.target.value)}
        >
          <option value="">Select…</option>
          {optionsFor(lookups?.country, a.country).map(o => (
            <option key={o.code} value={o.code}>{o.label}</option>
          ))}
        </select>
      </div>

      <SharedNote count={sharedBy} />
    </div>
  )
}

/** A line with its length shown against CR's cap. */
function CountedLine({ id, label, value, onChange }) {
  const over = value.length > LIMIT
  return (
    <div className="f-group">
      <div className="addr-lbl-row">
        <label className="f-label" htmlFor={`addr_${id}`}>{label}</label>
        <span className="addr-count" data-testid={`count-${id}`} data-over={String(over)}>
          {value.length}/{LIMIT}
        </span>
      </div>
      <input
        id={`addr_${id}`}
        className="f-input"
        value={value}
        aria-invalid={over ? 'true' : undefined}
        onChange={e => onChange(e.target.value)}
      />
      {over && (
        <span className="f-hint addr-over">
          The Companies Registry accepts {LIMIT} characters per line. Move the
          extra words onto another line rather than shortening them.
        </span>
      )}
    </div>
  )
}

/**
 * What a save will and will not touch, said BEFORE it is pressed.
 *
 * 4,446 companies share GSHK's registered office, because GSHK provides
 * registered-office services. An edit box with no warning on it reads as
 * "this changes my company" — and the server's copy-on-write means it really
 * does only change this one, which is worth saying out loud.
 */
function SharedNote({ count, readOnly = false }) {
  if (count <= 1) return null
  const n = count.toLocaleString()
  return (
    <div className="ab-note" role="note">
      Shared by <b>{n}</b> records.{' '}
      {readOnly
        ? 'Editing it here would affect only this one.'
        : 'Saving creates a separate address for this record only — the others are untouched.'}
    </div>
  )
}
