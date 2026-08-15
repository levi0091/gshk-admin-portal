import { useState, useEffect } from 'react'
import { api } from './api.js'

/**
 * GET `path`, cancelling the previous request whenever `path` changes.
 *
 * UAT W-8 — "if we toggle too fast on the dashboard there's a failure message".
 * Every tab, filter, sort and page change fires a fresh GET. Nothing cancelled
 * the previous one or asked whether it was still wanted, so two things went
 * wrong when responses came back out of order:
 *
 *   - a slow EARLIER response could resolve after a newer one and overwrite it,
 *     leaving the table showing a filter the user had already left;
 *   - a slow earlier FAILURE could paint the error banner over a view that had
 *     since loaded perfectly well. That is the failure message Levi saw — the
 *     request that failed was one nobody was waiting for any more.
 *
 * `signal.aborted` is the single check for both: once a run is superseded,
 * neither its value nor its error may touch state — including `loading`, which
 * a stale `finally` would otherwise clear while the current request was still
 * out, flashing empty data between the spinner and the real rows.
 *
 * Aborting is deliberate on top of ignoring: the ignored response would still
 * be downloaded and parsed, and on a slow connection a fast-toggling user
 * stacks up requests the backend is paying for.
 *
 * Path in, not a dep array: both callers already build the query string with
 * URLSearchParams, so the string IS the identity of the request. Passing the
 * same path twice must not refetch.
 */
export default function useAbortableGet(path) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')

    api.get(path, { signal: controller.signal })
      .then(payload => {
        if (controller.signal.aborted) return
        setData(payload)
        setLoading(false)
      })
      .catch(err => {
        // Superseded, not broken. Covers an abort rejection and a genuine
        // failure that lost the race alike, without having to recognise the
        // abort by error name — which differs across browsers and polyfills.
        if (controller.signal.aborted) return
        setError(err.message)
        setLoading(false)
      })

    return () => controller.abort()
  }, [path])

  return { data, loading, error }
}
