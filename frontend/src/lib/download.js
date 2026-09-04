import { api } from './api.js'

/**
 * Download a document instead of opening it in a tab.
 *
 * `window.open` on a PDF just renders it in the browser. The backend now signs
 * the URL with Storage's `download` flag (Content-Disposition: attachment), and
 * an anchor with `download` makes the browser save it rather than navigate.
 */
export async function downloadDocument(documentId, versionNumber = null) {
  // `versionNumber` fetches a SUPERSEDED version. The history list gives every
  // version a Download button, and without this every one of them signed the
  // current version's path — three buttons, one file, three names.
  const path = versionNumber == null
    ? `/documents/${documentId}/download`
    : `/documents/${documentId}/versions/${versionNumber}/download`
  const { url, file_name } = await api.get(path)
  saveUrl(url, file_name || '')
}

function saveUrl(url, fileName) {
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/**
 * Save the filled Form NAR1 for a filing.
 *
 * Fetched as a BLOB, not linked to: `/tpsi/filings/{id}/pdf` needs the bearer
 * token, and putting it in an href would leak it into history and the referrer.
 * The object URL is revoked straight after the click — the browser has already
 * taken the bytes by then, and leaving it holds the whole document in memory.
 *
 * The bytes are CR's own form, filled from the CR-validated snapshot
 * (services/nar1_form), which is the document that gets filed — not a summary
 * of it.
 */
export async function downloadFilingPdf(filingId, fileName = 'NAR1.pdf') {
  const blob = await api.blob(`/tpsi/filings/${filingId}/pdf`)
  const url = URL.createObjectURL(blob)
  try {
    saveUrl(url, fileName)
  } finally {
    URL.revokeObjectURL(url)
  }
}
