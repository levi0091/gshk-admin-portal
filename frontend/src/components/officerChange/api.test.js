import { describe, it, expect, vi, beforeEach } from 'vitest'

const api = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({})),
  patch: vi.fn(() => Promise.resolve({})),
  del: vi.fn(() => Promise.resolve({})),
  put: vi.fn(() => Promise.resolve({})),
  upload: vi.fn(() => Promise.resolve({})),
  blob: vi.fn(() => Promise.resolve(new Blob())),
}))
vi.mock('../../lib/api.js', () => ({ api }))

import { officerChangeApi as oc } from './api.js'

beforeEach(() => Object.values(api).forEach((fn) => fn.mockClear()))

describe('officerChangeApi', () => {
  it('opens a case with the form code and an optional first entry', async () => {
    await oc.create('e1', 'Nd2a')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes', { entity_id: 'e1', form_code: 'Nd2a' })
    await oc.create('e1', 'Nd2b', { kind: 'change' })
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes', {
      entity_id: 'e1', form_code: 'Nd2b', entry: { kind: 'change' },
    })
  })

  it('asks for pending cases by company or by person', async () => {
    await oc.pending({ entityId: 'e1' })
    expect(api.get).toHaveBeenLastCalledWith('/officer-changes/pending?entity_id=e1')
    await oc.pending({ personId: 'p1' })
    expect(api.get).toHaveBeenLastCalledWith('/officer-changes/pending?person_id=p1')
  })

  it.each([
    ['get', () => oc.get('c1'), 'get', '/officer-changes/c1'],
    ['patch', () => oc.patch('c1', { signing_method: 'manual' }), 'patch', '/officer-changes/c1'],
    ['addEntry', () => oc.addEntry('c1', {}), 'post', '/officer-changes/c1/entries'],
    ['updateEntry', () => oc.updateEntry('c1', 'n1', {}), 'patch', '/officer-changes/c1/entries/n1'],
    ['removeEntry', () => oc.removeEntry('c1', 'n1'), 'del', '/officer-changes/c1/entries/n1'],
    ['setKyc', () => oc.setKyc('c1', 'n1', true), 'post', '/officer-changes/c1/entries/n1/kyc'],
    ['removeDocument', () => oc.removeDocument('c1', 'd1'), 'del', '/officer-changes/c1/documents/d1'],
    ['documentUrl', () => oc.documentUrl('c1', 'd1'), 'get', '/officer-changes/c1/documents/d1/download'],
    ['preview', () => oc.preview('c1'), 'blob', '/officer-changes/c1/preview?audience=client'],
    ['preview staff', () => oc.preview('c1', 'staff'), 'blob', '/officer-changes/c1/preview?audience=staff'],
    ['recipients', () => oc.recipients('c1'), 'get', '/officer-changes/c1/verification/recipients'],
    ['send', () => oc.send('c1', {}), 'post', '/officer-changes/c1/verification/send'],
    ['delivery', () => oc.delivery('c1'), 'get', '/officer-changes/c1/verification/delivery'],
    ['recordResponse', () => oc.recordResponse('c1', {}), 'post', '/officer-changes/c1/verification/response'],
    ['validate', () => oc.validate('c1'), 'post', '/officer-changes/c1/validate'],
    ['markChecked', () => oc.markChecked('c1'), 'post', '/officer-changes/c1/mark-checked'],
    ['sign', () => oc.sign('c1'), 'post', '/officer-changes/c1/sign'],
    ['submit', () => oc.submit('c1'), 'post', '/officer-changes/c1/submit'],
    ['recordFiling', () => oc.recordFiling('c1', {}), 'post', '/officer-changes/c1/record-filing'],
    ['undo', () => oc.undo('c1'), 'post', '/officer-changes/c1/undo'],
    ['retryApply', () => oc.retryApply('c1'), 'post', '/officer-changes/c1/apply'],
    ['close', () => oc.close('c1', 'x'), 'post', '/officer-changes/c1/close'],
    ['refreshCrStatus', () => oc.refreshCrStatus('c1'), 'post', '/tpsi/cases/c1/refresh-status'],
    // Jacqueline's feedback (1 Oct 2026)
    ['setSendWithEmail', () => oc.setSendWithEmail('c1', 'd1', true), 'patch', '/officer-changes/c1/documents/d1'],
    ['proceed', () => oc.proceed('c1', 'why'), 'post', '/officer-changes/c1/verification/proceed'],
    ['setEffectiveDate', () => oc.setEffectiveDate('c1', 'n1', '2026-10-01'), 'put', '/officer-changes/c1/entries/n1/effective-date'],
  ])('%s calls %s', async (_name, call, verb, path) => {
    await call()
    expect(api[verb].mock.calls.at(-1)[0]).toBe(path)
  })

  it('sends an empty body to sign, and confirm on the irreversible steps', async () => {
    await oc.sign('c1')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/sign', {})
    await oc.submit('c1')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/submit', { confirm: true })
    await oc.recordFiling('c1', { caseNo: '1' })
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/record-filing', {
      receipt: { caseNo: '1' }, confirm: true,
    })
    await oc.undo('c1')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/undo', { confirm: true })
  })

  it.each([
    ['uploadDocument', () => oc.uploadDocument('c1', 'n1', new Blob(['x']), 'board_resolution'),
      '/officer-changes/c1/entries/n1/documents', ['file', 'document_type_code']],
    ['uploadSignedForm', () => oc.uploadSignedForm('c1', new Blob(['x'])),
      '/officer-changes/c1/signed-form', ['file']],
    ['uploadReceipt', () => oc.uploadReceipt('c1', new Blob(['x'])),
      '/officer-changes/c1/receipt', ['file']],
    ['uploadCaseDocument', () => oc.uploadCaseDocument('c1', new Blob(['x']), 'board_resolution', true),
      '/officer-changes/c1/documents', ['file', 'document_type_code', 'send_with_email']],
  ])('%s posts multipart to its route', async (_name, call, path, fields) => {
    await call()
    const [calledPath, form] = api.upload.mock.calls.at(-1)
    expect(calledPath).toBe(path)
    fields.forEach((field) => expect(form.has(field)).toBe(true))
  })
})

describe('officerChangeApi — bodies added for Jacqueline\'s feedback', () => {
  it('sends the ND2B line key only when there is one, and the route for mark-checked', async () => {
    await oc.setEffectiveDate('c1', 'n1', '2026-10-01', 'email')
    expect(api.put).toHaveBeenLastCalledWith('/officer-changes/c1/entries/n1/effective-date',
      { effective_date: '2026-10-01', item_key: 'email' })
    await oc.markChecked('c1', 'esign')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/mark-checked',
      { signing_method: 'esign' })
    await oc.markChecked('c1')
    expect(api.post).toHaveBeenLastCalledWith('/officer-changes/c1/mark-checked', {})
  })
})
