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

/**
 * The same form, for a CASE rather than a filing.
 *
 * Needed because a case at Client Verification — the FIRST stage since
 * 2026-09-17 — usually has no filing row yet, so there is no id to download by.
 * The case endpoint builds the return in memory when it has to, and still
 * prefers CR's validated copy whenever one exists, so this and
 * `downloadFilingPdf` hand over the same bytes wherever both would work.
 */
export async function downloadCasePdf(caseId, fileName = 'NAR1.pdf') {
  const blob = await api.blob(`/cases/${caseId}/verification/preview`)
  const url = URL.createObjectURL(blob)
  try {
    saveUrl(url, fileName)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * The return exactly as the Companies Registry validated it — the CLEAN copy.
 *
 * `highlight=false`, deliberately: the viewer at Data Verification boxes what
 * moved since the client approved, and those boxes are a review aid, not part
 * of the return. A file someone saves is a file someone forwards, and a
 * statutory form with orange boxes on it is not the form that was filed.
 */
export async function downloadValidatedPdf(caseId, fileName = 'NAR1-validated.pdf') {
  const blob = await api.blob(`/cases/${caseId}/validation/preview?highlight=false`)
  const url = URL.createObjectURL(blob)
  try {
    saveUrl(url, fileName)
  } finally {
    URL.revokeObjectURL(url)
  }
}
