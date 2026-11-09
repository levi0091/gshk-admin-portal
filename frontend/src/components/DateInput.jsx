import { useEffect, useRef, useState } from 'react'

/**
 * A date box that always reads DD/MM/YYYY (Levi, UAT 2026-11-09: "this date
 * format dd/mm/yyyy should be used for all date inputs").
 *
 * WHY NOT `<input type="date">`. A native date input draws its own text in the
 * BROWSER's locale, and nothing a page sets can change that — not `lang`, not
 * CSS. On an en-US browser it shows mm/dd/yyyy, so "11/08/2026" on the ND2A
 * drawer meant 8 November to the portal and 11 August to the person reading it.
 * A statutory date that reads two ways is the failure, so the box is text.
 *
 * THE CONTRACT IS THE NATIVE ONE, so a call site swaps `<input type="date">`
 * for this and changes nothing else: `value` is ISO `YYYY-MM-DD` (or ''), and
 * `onChange` receives an event-like `{ target: { value } }` carrying ISO — ''
 * while the text is incomplete or not a real day, exactly as a native input
 * reports. `min` / `max` (ISO) bound the calendar.
 *
 * Typing: digits only, the slashes are inserted. Pasting or typing an ISO date
 * is accepted and reformatted. The calendar button opens the browser's own
 * picker (`showPicker`) on a hidden native input, so nobody loses the calendar.
 */
export function isoToDisplay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso ?? ''))
  return m ? `${m[3]}/${m[2]}/${m[1]}` : ''
}

function realDay(y, m, d) {
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}

/** "dd/mm/yyyy" (or an ISO date) -> "yyyy-mm-dd", or '' if not a real day. */
export function displayToIso(text) {
  const t = String(text ?? '').trim()
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t)
  if (m) return realDay(+m[1], +m[2], +m[3]) ? t : ''
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(t)
  if (!m) return ''
  const [d, mo, y] = [+m[1], +m[2], +m[3]]
  if (y < 1000 || !realDay(y, mo, d)) return ''
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** Digits typed so far -> "dd/mm/yyyy" with the slashes in place. */
function mask(raw) {
  const digits = String(raw).replace(/\D/g, '').slice(0, 8)
  if (digits.length <= 2) return digits
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
}

export default function DateInput({
  value, onChange, min, max, className = 'f-input', disabled, style, ...rest
}) {
  const iso = value ?? ''
  const [text, setText] = useState(() => isoToDisplay(iso))
  const picker = useRef(null)

  // Follow the value when it moves from OUTSIDE (a reset, a default, the
  // calendar). Not while the operator is mid-way through typing: then the value
  // is '' because the text is incomplete, and resyncing would wipe their typing.
  useEffect(() => {
    if (iso !== displayToIso(text)) setText(isoToDisplay(iso))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [iso])

  function emit(next) {
    if (next !== iso) onChange?.({ target: { value: next } })
  }

  function typed(e) {
    const raw = e.target.value
    // A whole ISO date (pasted, or set programmatically) is taken as it is,
    // and one being TYPED as yyyy-mm-dd is left alone until it is whole.
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw.trim())) {
      const next = displayToIso(raw)
      setText(next ? isoToDisplay(next) : raw)
      emit(next)
      return
    }
    // Four digits then "-" is a year typed first: the mask had already put a
    // slash after the first two, so undo it and switch to yyyy-mm-dd.
    const digits = raw.replace(/\D/g, '')
    if (raw.endsWith('-') && digits.length === 4 && !text.includes('-')) {
      setText(`${digits}-`)
      emit('')
      return
    }
    if (/^\d{4}-\d{0,2}(-\d{0,1})?$/.test(raw)) {
      setText(raw)
      emit('')
      return
    }
    // Deleting a slash must not be undone by the mask putting it straight back.
    const shown = raw.length < text.length && text.endsWith('/') && !raw.endsWith('/')
      ? mask(raw.replace(/\D$/, '')) : mask(raw)
    setText(shown)
    emit(displayToIso(shown))
  }

  function openCalendar() {
    const el = picker.current
    if (!el || disabled) return
    try {
      if (typeof el.showPicker === 'function') el.showPicker()
      else el.click()
    } catch { el.focus() }
  }

  const invalid = text.length === 10 && !displayToIso(text)
  return (
    <span className="date-input" style={style}>
      <input
        {...rest}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="dd/mm/yyyy"
        maxLength={10}
        // Inert on a text box; carried so callers and tests can read the bound
        // the calendar enforces.
        min={min}
        max={max}
        className={className}
        value={text}
        disabled={disabled}
        aria-invalid={invalid || rest['aria-invalid'] || undefined}
        onChange={typed}
      />
      <button type="button" className="date-input-cal" onClick={openCalendar}
              disabled={disabled} aria-label="Open calendar" tabIndex={-1}>
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1.5" y="3" width="13" height="11.5" rx="1.5" fill="none" stroke="currentColor" />
          <path d="M1.5 6.5h13M5 1.5v3M11 1.5v3" stroke="currentColor" fill="none" />
        </svg>
      </button>
      <input
        ref={picker}
        type="date"
        className="date-input-native"
        tabIndex={-1}
        aria-hidden="true"
        value={iso}
        min={min}
        max={max}
        disabled={disabled}
        onChange={e => { setText(isoToDisplay(e.target.value)); emit(e.target.value) }}
      />
    </span>
  )
}
