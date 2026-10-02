// The officer-change (ND2A / ND2B) endpoints, one method per route of the
// plan's contract C-3. Every path lives here so the page, its stages and the
// profile entry points cannot drift apart on a URL.
import { api } from '../../lib/api.js'

const base = (id) => `/officer-changes/${id}`

function upload(path, fields) {
  const form = new FormData()
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== undefined && value !== null) form.append(key, value)
  })
  return api.upload(path, form)
}

export const officerChangeApi = {
  create: (entityId, formCode, entry) =>
    api.post('/officer-changes', {
      entity_id: entityId,
      form_code: formCode,
      ...(entry ? { entry } : {}),
    }),
  pending: ({ entityId, personId } = {}) => {
    const params = new URLSearchParams()
    if (entityId) params.set('entity_id', entityId)
    if (personId) params.set('person_id', personId)
    return api.get(`/officer-changes/pending?${params.toString()}`)
  },
  get: (id, options) => api.get(base(id), options),
  patch: (id, body) => api.patch(base(id), body),

  addEntry: (id, entry) => api.post(`${base(id)}/entries`, entry),
  updateEntry: (id, entryId, patch) => api.patch(`${base(id)}/entries/${entryId}`, patch),
  removeEntry: (id, entryId) => api.del(`${base(id)}/entries/${entryId}`),
  setKyc: (id, entryId, cleared) =>
    api.post(`${base(id)}/entries/${entryId}/kyc`, { cleared }),

  uploadDocument: (id, entryId, file, documentTypeCode) =>
    upload(`${base(id)}/entries/${entryId}/documents`, {
      file,
      document_type_code: documentTypeCode,
    }),
  removeDocument: (id, docId) => api.del(`${base(id)}/documents/${docId}`),
  documentUrl: (id, docId) => api.get(`${base(id)}/documents/${docId}/download`),

  // A Blob; the caller makes and revokes the object URL.
  preview: (id, audience = 'client') =>
    api.blob(`${base(id)}/preview?audience=${encodeURIComponent(audience)}`),

  recipients: (id) => api.get(`${base(id)}/verification/recipients`),
  send: (id, body) => api.post(`${base(id)}/verification/send`, body),
  delivery: (id) => api.get(`${base(id)}/verification/delivery`),
  recordResponse: (id, body) => api.post(`${base(id)}/verification/response`, body),

  validate: (id) => api.post(`${base(id)}/validate`, {}),
  markChecked: (id) => api.post(`${base(id)}/mark-checked`, {}),
  sign: (id) => api.post(`${base(id)}/sign`, {}),
  uploadSignedForm: (id, file) => upload(`${base(id)}/signed-form`, { file }),
  submit: (id) => api.post(`${base(id)}/submit`, { confirm: true }),
  uploadReceipt: (id, file) => upload(`${base(id)}/receipt`, { file }),
  recordFiling: (id, receipt) =>
    api.post(`${base(id)}/record-filing`, { receipt, confirm: true }),
  undo: (id) => api.post(`${base(id)}/undo`, { confirm: true }),
  // Re-runs an unfinished profile update of a FILED form (idempotent per entry).
  retryApply: (id) => api.post(`${base(id)}/apply`, { confirm: true }),
  close: (id, reason) => api.post(`${base(id)}/close`, { reason }),

  // CR's register is asked through the route NAR1 already uses; it is keyed on
  // the case, not the form.
  refreshCrStatus: (id) => api.post(`/tpsi/cases/${id}/refresh-status`, {}),
}
