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
    throw new Error(err.detail || 'API error')
  }
  return resp.json()
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
    throw new Error(err.detail || 'Upload failed')
  }
  return resp.json()
}

export const api = {
  get: (path) => apiFetch(path),
  post: (path, body) => apiFetch(path, { method: 'POST', body: JSON.stringify(body) }),
  put: (path, body) => apiFetch(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: (path, body) => apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) }),
  del: (path) => apiFetch(path, { method: 'DELETE' }),
  upload: apiUpload,
}
