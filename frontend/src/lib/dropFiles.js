/**
 * Getting files out of a drop, wherever they were dragged from.
 *
 * GSHK (2026-11-21) want to drag "from anywhere": the desktop, an attachment
 * in an open Outlook message, or one in an open Gmail message. Those arrive in
 * three different shapes, and the browser lets us read them only DURING the
 * drop event, so `readDrop` is synchronous and copies out everything first.
 *
 *  - Desktop / Finder / Explorer: `dataTransfer.files`.
 *  - Outlook for Windows (classic and new) in Chrome or Edge: also `files`.
 *    Chromium turns Outlook's "virtual file" into a real File.
 *  - Gmail, Outlook on the web: NO file at all. The page offers a
 *    `DownloadURL` ("mime:name:url") pointing at the mail provider's servers.
 *    We try to fetch it; the provider will normally refuse a request from
 *    another site (CORS), and when it does the operator is told the one
 *    reliable route: save the attachment first, then drop the saved file.
 */

/** True when the thing being dragged is a file or a downloadable attachment,
 *  not a stretch of selected text or a link inside the portal. */
export function looksLikeFileDrag(dt) {
  const types = Array.from(dt?.types || []).map(t => String(t).toLowerCase())
  return types.includes('files') || types.includes('downloadurl')
}

/**
 * Everything readable from a drop, synchronously.
 * `{ files: File[], remote: { name, url, mime } | null }`
 */
export function readDrop(dt) {
  let files = []
  // `items` first: in Chromium it is how an Outlook virtual file comes through,
  // and `getAsFile` returns null for directory entries, which we skip.
  if (dt?.items && dt.items.length) {
    for (const item of Array.from(dt.items)) {
      if (item.kind === 'file') {
        const f = item.getAsFile()
        if (f) files.push(f)
      }
    }
  }
  if (!files.length && dt?.files?.length) files = Array.from(dt.files)

  let remote = null
  if (!files.length) {
    remote = parseDownloadUrl(safeGet(dt, 'DownloadURL'))
      || urlOnly(safeGet(dt, 'text/uri-list'))
  }
  return { files, remote }
}

function safeGet(dt, type) {
  try { return dt?.getData?.(type) || '' } catch { return '' }
}

/** "application/pdf:invoice.pdf:https://…" — the URL keeps its own colons. */
export function parseDownloadUrl(value) {
  const v = String(value || '')
  const first = v.indexOf(':')
  const second = first < 0 ? -1 : v.indexOf(':', first + 1)
  if (first < 0 || second < 0) return null
  const url = v.slice(second + 1)
  if (!/^https?:\/\//i.test(url)) return null
  return { mime: v.slice(0, first), name: v.slice(first + 1, second) || 'attachment', url }
}

function urlOnly(list) {
  const url = String(list || '').split(/\r?\n/).find(l => /^https?:\/\//i.test(l.trim()))
  if (!url) return null
  const name = decodeURIComponent(url.trim().split('?')[0].split('/').pop() || '') || 'attachment'
  return { mime: '', name, url: url.trim() }
}

export const REMOTE_REFUSED =
  'Your mail provider would not let the portal read that attachment directly. '
  + 'Download it (or drag it onto your desktop) first, then drop the saved file here.'

/** Fetch a dragged attachment into a File, or throw an Error saying what to do. */
export async function fetchRemote(remote, fetchImpl = globalThis.fetch) {
  let resp
  try {
    resp = await fetchImpl(remote.url, { credentials: 'include' })
  } catch {
    throw new Error(REMOTE_REFUSED)
  }
  if (!resp || !resp.ok) throw new Error(REMOTE_REFUSED)
  const blob = await resp.blob()
  return new File([blob], remote.name, { type: remote.mime || blob.type || '' })
}
