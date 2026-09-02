import { supabase } from './supabaseClient'

const BASE = import.meta.env.VITE_API_URL

async function getAuthHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  if (!session) throw new Error('Not authenticated')
  return { Authorization: `Bearer ${session.access_token}` }
}

export async function apiFetch(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(await getAuthHeaders()),
    ...(options.headers || {}),
  }
  const resp = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    // The status rides on the error because the NAR1 workflow has to tell four
    // failures apart and act differently on each: 400 is an inline fix, 409 is
    // an expired TPSI password or a refused submit gate, 502 is a CR fault that
    // must NEVER be auto-retried, and 503 is the CR TEST window being shut.
    // Without this they all arrive as an indistinguishable Error(message).
    const e = describeApiError(err.detail, resp.statusText)
    e.status = resp.status
    throw e
  }
  return resp.json()
}

/**
 * Turn FastAPI's `detail` into a readable Error, whatever shape it arrived in.
 *
 * `detail` is NOT always a string. Three shapes reach us, and passing any of
 * the structured ones to `new Error()` yields the literal text
 * "[object Object]" — which is what the NAR1 workflow showed instead of the
 * mapper's field-by-field reasons, the most useful error in the app.
 *
 *   "a plain string"            -> the message
 *   {message, problems: [...]}  -> our own structured 400s (tpsi.py prepare,
 *                                  cases.py manual-submit)
 *   [{loc, msg, type}, ...]     -> FastAPI's own 422 validation body
 *
 * `problems` is preserved on the error so the caller can list every one at
 * once — which is the entire reason the backend collects them all.
 */
export function describeApiError(detail, fallback = 'API error') {
  if (detail == null) return new Error(fallback || 'API error')

  if (typeof detail === 'string') return new Error(detail)

  // FastAPI request-validation errors: an array of {loc, msg}.
  if (Array.isArray(detail)) {
    const problems = detail.map(d => {
      if (typeof d === 'string') return d
      const field = Array.isArray(d?.loc)
        ? d.loc.filter(p => p !== 'body').join('.')
        : null
      return field ? `${field}: ${d?.msg ?? 'invalid'}` : (d?.msg ?? JSON.stringify(d))
    })
    const e = new Error(
      problems.length === 1 ? problems[0] : `${problems.length} fields need correcting`)
    e.problems = problems
    return e
  }

  if (typeof detail === 'object') {
    const problems = Array.isArray(detail.problems) ? detail.problems : null
    const message = detail.message || detail.detail || detail.error
      || (problems
        ? `${problems.length} problem${problems.length === 1 ? '' : 's'} found`
        : JSON.stringify(detail))
    const e = new Error(message)
    if (problems) e.problems = problems
    // WHAT KIND of refusal this was. The backend distinguishes a CR validation
    // fault from a signature fault from a locked account, and they have
    // different remedies in different places — carrying only the message would
    // send the operator to edit a form when the problem is their CR account.
    if (detail.kind) e.kind = detail.kind
    // WHICH GATE refused, for the 409s the submit gate raises: `drift`,
    // `record_unusable` or `check_failed`. They are three different situations
    // with three different remedies — and one of them (check_failed) must NOT
    // offer to restart verification, because restarting cannot fix a company
    // record that would not load.
    if (detail.reason) e.reason = detail.reason
    // Spec §6's drift refusal: which filed particulars moved, with both values.
    // Carried like `problems` rather than flattened into the message — the
    // Submission stage renders it as a table, and a sentence cannot show two
    // values per row.
    if (Array.isArray(detail.differences)) e.differences = detail.differences
    return e
  }

  return new Error(String(detail))
}

/** Multipart upload — must NOT set Content-Type; the browser adds the boundary. */
async function apiUpload(path, formData) {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: await getAuthHeaders(),
    body: formData,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    const e = describeApiError(err.detail, 'Upload failed')
    e.status = resp.status
    throw e
  }
  return resp.json()
}

/**
 * GET a binary body (the NAR1 PDF preview).
 *
 * Separate from `get` because `apiFetch` calls `resp.json()`, which would throw
 * on a PDF. Returns a Blob the caller turns into an object URL — the bytes
 * never touch state, and the caller is responsible for revoking the URL.
 */
async function apiBlob(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...(await getAuthHeaders()), ...(options.headers || {}) },
  })
  if (!resp.ok) {
    // An error body IS json even when the success body is not.
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    const e = describeApiError(err.detail, 'Request failed')
    e.status = resp.status
    throw e
  }
  return resp.blob()
}

export const api = {
  // `options` carries the AbortSignal from useAbortableGet; apiFetch already
  // spreads it into fetch(), so nothing else needs to change.
  get: (path, options) => apiFetch(path, options),
  post: (path, body) => apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  put: (path, body) => apiFetch(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: (path, body) => apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) }),
  del: (path) => apiFetch(path, { method: 'DELETE' }),
  upload: apiUpload,
  blob: apiBlob,
}
