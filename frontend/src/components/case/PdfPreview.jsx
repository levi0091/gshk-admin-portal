import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { describeError } from './workflow.js'

// Zoom bounds for the embedded preview. 60% still shows a full A4 page on a
// laptop; past 200% the object viewport is taller than any screen and the
// operator is scrolling a scroller.
export const ZOOM_MIN = 60
export const ZOOM_MAX = 200
export const ZOOM_STEP = 20

/**
 * The frame's height at 100%, in CSS pixels.
 *
 * 1035 was 30% too tall (Levi 2026-09-09) — a partial reversal of the raise
 * made two days earlier. At 1035px the controls below the frame sat below the
 * fold on a laptop, and reaching them meant scrolling PAST an <object> that
 * swallows the wheel. No embedded height that leaves room for the controls
 * holds a NINE-page return, so the frame was never where the full check is
 * done — `Open full screen` is — and 725 still clears a full A4 page at 100%.
 */
export const FRAME_HEIGHT = 725

/**
 * A PDF from an authenticated endpoint, as an object URL.
 *
 * Fetched as a blob so the bearer token is never put in a URL, and the object
 * URL is revoked when the path or key changes or the component goes — leaving
 * it holds the whole return in memory.
 *
 * `key` is whatever should force a re-fetch for the same path: the case's
 * `updated_at`, a validation timestamp. Returns `{ url, error }`; both null
 * while loading, so a caller can always tell "rendering" from "failed".
 */
export function usePdfBlob(path, key) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!path) return undefined
    let objectUrl = null
    let cancelled = false
    setError(null)
    setUrl(null)
    api.blob(path)
      .then(b => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(b)
        setUrl(objectUrl)
      })
      .catch(e => { if (!cancelled) setError(describeError(e)) })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path, key])

  return { url, error }
}

/**
 * The embedded return: a toolbar (file name, what this copy is, zoom) over the
 * browser's own PDF viewer — or, in the same place, why there is nothing to
 * show, or that it is still rendering.
 *
 * `pills` are `{ label, tone }` where tone is '' | 'ok' | 'warn': the facts a
 * reader needs about WHICH copy this is before reading it.
 */
export default function PdfFrame({ url, error, fileName, pills = [], label,
                                   emptyText = 'Rendering the preview…' }) {
  const [zoom, setZoom] = useState(100)

  if (error) {
    // The pane saying it has nothing to show, where the document would have
    // been. Not an alert: nothing the operator did was refused.
    return (
      <div className="card-note card-note-warn" role="status">
        <b>The preview could not be rendered.</b>
        <div style={{ marginTop: 4 }}>{error.message}</div>
        {error.hint && <div style={{ marginTop: 4 }}>{error.hint}</div>}
      </div>
    )
  }
  if (!url) {
    return <div className="empty-state" style={{ padding: 24 }}>{emptyText}</div>
  }
  return (
    <>
      <div className="pdf-toolbar">
        <span className="pdf-fname">{fileName}</span>
        {pills.map(p => (
          <span key={p.label} className={`pdf-pill${p.tone ? ` ${p.tone}` : ''}`}>
            {p.label}
          </span>
        ))}
        <span className="pdf-tb-spacer" />
        <span className="pdf-zoom">
          <button type="button" aria-label="Zoom out" disabled={zoom <= ZOOM_MIN}
                  onClick={() => setZoom(z => Math.max(ZOOM_MIN, z - ZOOM_STEP))}>−</button>
          <span className="zval">{zoom}%</span>
          <button type="button" aria-label="Zoom in" disabled={zoom >= ZOOM_MAX}
                  onClick={() => setZoom(z => Math.min(ZOOM_MAX, z + ZOOM_STEP))}>+</button>
        </span>
      </div>
      {/* Zoom grows the VIEWPORT, not a CSS transform. Scaling the element
          would scale its scrollbars and clip the page; a taller frame is what
          the embedded viewer actually reads as bigger. */}
      <object data={url} type="application/pdf" aria-label={label}
              className="pdf-frame"
              style={{ height: Math.round(FRAME_HEIGHT * zoom / 100) }}>
        {/* Some browsers refuse to embed; a link is not a dead end. */}
        <a href={url} target="_blank" rel="noreferrer">Open the {label}</a>
      </object>
    </>
  )
}
