import { api } from './api.js'

/**
 * Download a document instead of opening it in a tab.
 *
 * `window.open` on a PDF just renders it in the browser. The backend now signs
 * the URL with Storage's `download` flag (Content-Disposition: attachment), and
 * an anchor with `download` makes the browser save it rather than navigate.
 */
export async function downloadDocument(documentId) {
  const { url, file_name } = await api.get(`/documents/${documentId}/download`)
  const a = document.createElement('a')
  a.href = url
  a.download = file_name || ''
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
