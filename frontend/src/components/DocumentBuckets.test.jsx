import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn() },
}))
vi.mock('../lib/download.js', () => ({ downloadDocument: vi.fn() }))

import { api } from '../lib/api.js'
import { downloadDocument } from '../lib/download.js'
import DocumentBuckets from './DocumentBuckets.jsx'
import { DEFAULT_LIMITS } from '../lib/documentSections.js'

const BUCKETS = [
  { key: 'payments', label: 'Payments', description: 'Payment slips',
    suggestions: ['Payment Slip'] },
  { key: 'maintenance', label: 'Maintenance', description: 'Filed forms',
    suggestions: ['Filed ND2A', 'Filed ND2B'] },
  { key: 'other', label: 'Other Documents', description: '', suggestions: [], fallback: true },
]
const LIMITS = { ...DEFAULT_LIMITS, blocked_extensions: ['exe', 'js'] }

const doc = (id, extra = {}) => ({
  id, file_name: `${id}.pdf`, bucket: 'payments', tags: [], title: null,
  status: 'active', current_version: 1, uploaded_at: `2026-11-${10 + Number(id.slice(1))}T02:00:00Z`,
  document_versions: [], ...extra,
})

function renderBuckets(props = {}) {
  return render(
    <DocumentBuckets ownerKind="entity" ownerId="e1" ownerName="Skyline Capital"
                     documents={[doc('d1'), doc('d2')]} buckets={BUCKETS} limits={LIMITS}
                     canEdit canRemove canDownload {...props} />)
}

const region = name => screen.getByRole('region', { name: new RegExp(`^${name}`) })
const pdf = name => new File(['%PDF-1.7'], name, { type: 'application/pdf' })

let seq = 0
beforeEach(() => {
  vi.clearAllMocks()
  seq = 0
  api.upload.mockImplementation((_path, form) => {
    seq += 1
    const file = form.get('file')
    return Promise.resolve({
      id: `new${seq}`, file_name: file.name, bucket: form.get('bucket'), tags: [],
      status: 'active', current_version: 1, uploaded_at: '2026-11-21T03:00:00Z',
    })
  })
  api.patch.mockImplementation((_path, body) => Promise.resolve(body.ids.map(id => ({
    id,
    ...(body.bucket ? { bucket: body.bucket } : {}),
    ...('title' in body ? { title: body.title || null } : {}),
    ...(body.add_tags ? { tags: body.add_tags } : {}),
  }))))
  api.del.mockResolvedValue({})
})

describe('DocumentBuckets — layout', () => {
  it('lists each bucket newest upload first, hides the empty fallback', () => {
    renderBuckets({ documents: [doc('d1'), doc('d3'), doc('d2')] })
    const names = within(region('Payments')).getAllByRole('button', { name: /^d\d\.pdf$/ })
      .map(b => b.textContent)
    expect(names).toEqual(['d3.pdf', 'd2.pdf', 'd1.pdf'])
    expect(within(region('Maintenance')).getByText(/Nothing here yet/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /^Other Documents/ })).toBeNull()
  })

  it('shows the fallback bucket when it holds something, so its files can be moved out', () => {
    renderBuckets({ documents: [doc('d1', { bucket: 'other' })] })
    expect(within(region('Other Documents')).getByText('d1.pdf')).toBeInTheDocument()
    // It is not an upload target.
    expect(within(region('Other Documents')).queryByRole('button', { name: /Upload/ })).toBeNull()
  })

  it('previews five rows and expands in place', async () => {
    const user = userEvent.setup()
    const many = Array.from({ length: 8 }, (_, i) => doc(`d${i + 1}`))
    renderBuckets({ documents: many })
    expect(within(region('Payments')).getAllByRole('listitem')).toHaveLength(5)
    await user.click(screen.getByRole('button', { name: 'Show all 8' }))
    expect(within(region('Payments')).getAllByRole('listitem')).toHaveLength(8)
    await user.click(screen.getByRole('button', { name: 'Show fewer' }))
    expect(within(region('Payments')).getAllByRole('listitem')).toHaveLength(5)
  })

  it('offers a reader the files and nothing that changes them', () => {
    renderBuckets({ canEdit: false, canRemove: false, canDownload: true,
                    documents: [doc('d1', { title: 'March slip', tags: ['Payment Slip'] })] })
    expect(screen.getByRole('button', { name: 'Download d1.pdf' })).toBeInTheDocument()
    expect(screen.getByText('March slip')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('button', { name: /Upload|Remove|Add a tag/ })).toBeNull()
    expect(screen.queryByText(/Drag files anywhere/)).toBeNull()
  })

  it('downloads an earlier version from the row', async () => {
    const user = userEvent.setup()
    renderBuckets({ documents: [doc('d1', { current_version: 2, document_versions: [
      { id: 'v1', version_number: 1, created_at: '2026-01-02T00:00:00Z' },
      { id: 'v2', version_number: 2, created_at: '2026-11-11T00:00:00Z' },
    ] })] })
    await user.click(screen.getByRole('button', { name: 'v2' }))
    await user.click(screen.getByRole('button', { name: /^v1 · / }))
    expect(downloadDocument).toHaveBeenCalledWith('d1', 1)
  })
})

describe('DocumentBuckets — upload', () => {
  it('uploads picked files into the bucket, then selects them for bulk tagging', async () => {
    const user = userEvent.setup()
    renderBuckets()
    await user.upload(screen.getByLabelText('Choose files for Maintenance'),
                      [pdf('nd2a.pdf'), pdf('nd2b.pdf')])

    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(2))
    for (const [path, form] of api.upload.mock.calls) {
      expect(path).toBe('/companies/e1/documents')
      expect(form.get('bucket')).toBe('maintenance')
    }
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    expect(within(bar).getByText(/just uploaded/)).toBeInTheDocument()
    expect(within(bar).getByText('2')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Select nd2a.pdf' })).toBeChecked()
    expect(screen.getByText(/2 uploaded to Maintenance/)).toBeInTheDocument()
  })

  it('refuses a drop of more than 20 files whole, before sending any', async () => {
    const user = userEvent.setup()
    renderBuckets()
    const files = Array.from({ length: 21 }, (_, i) => pdf(`f${i}.pdf`))
    await user.upload(screen.getByLabelText('Choose files for Payments'), files)
    expect(await screen.findByRole('alert')).toHaveTextContent(/21 files.*Up to 20/)
    expect(api.upload).not.toHaveBeenCalled()
  })

  it('sends twenty', async () => {
    const user = userEvent.setup()
    renderBuckets()
    const files = Array.from({ length: 20 }, (_, i) => pdf(`f${i}.pdf`))
    await user.upload(screen.getByLabelText('Choose files for Payments'), files)
    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(20))
  })

  it('skips only what it must, and says why beside the file', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderBuckets()
    await user.upload(screen.getByLabelText('Choose files for Payments'), [
      pdf('slip.pdf'),
      new File(['x'], 'setup.exe'),
      new File([], 'blank.docx'),
      new File(['a,b'], 'ledger.csv', { type: 'text/csv' }),
      new File(['x'], 'photo.HEIC'),
    ])
    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(3))
    const sent = api.upload.mock.calls.map(([, f]) => f.get('file').name)
    expect(sent.sort()).toEqual(['ledger.csv', 'photo.HEIC', 'slip.pdf'])
    expect(await screen.findByText(/\.exe files can run code/)).toBeInTheDocument()
    expect(screen.getByText('The file is empty')).toBeInTheDocument()
    expect(screen.getByText(/3 uploaded to Payments · 2 not uploaded/)).toBeInTheDocument()
  })

  it('reports a file the server refused without losing the rest', async () => {
    const user = userEvent.setup()
    api.upload.mockImplementationOnce(() => Promise.reject(new Error('Storage is unavailable')))
    renderBuckets()
    await user.upload(screen.getByLabelText('Choose files for Payments'), [pdf('a.pdf'), pdf('b.pdf')])
    expect(await screen.findByText('Storage is unavailable')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/1 uploaded to Payments · 1 not uploaded/))
      .toBeInTheDocument())
  })
})

describe('DocumentBuckets — dragging files onto the page', () => {
  const fileDrag = files => ({
    types: ['Files'], files, items: files.map(f => ({ kind: 'file', getAsFile: () => f })),
    getData: () => '', dropEffect: 'none',
  })

  it('opens the bucket targets when a FILE is dragged over the window, and uploads where it lands', async () => {
    renderBuckets()
    const dt = fileDrag([pdf('slip.pdf')])
    act(() => { fireEvent.dragEnter(window, { dataTransfer: dt }) })
    const overlay = screen.getByRole('dialog', { name: 'Drop files into a bucket' })
    expect(within(overlay).getByText('Skyline Capital')).toBeInTheDocument()
    expect(within(overlay).queryByText('Other Documents')).toBeNull()

    fireEvent.drop(screen.getByTestId('drop-payments'), { dataTransfer: dt })
    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(1))
    expect(api.upload.mock.calls[0][1].get('bucket')).toBe('payments')
    expect(screen.queryByRole('dialog', { name: 'Drop files into a bucket' })).toBeNull()
  })

  it('ignores a drag of selected text', () => {
    renderBuckets()
    act(() => { fireEvent.dragEnter(window, { dataTransfer: { types: ['text/plain'] } }) })
    expect(screen.queryByRole('dialog', { name: 'Drop files into a bucket' })).toBeNull()
  })

  it('stays out of the way of an open modal', () => {
    renderBuckets()
    const modal = document.createElement('div')
    modal.className = 'overlay'
    document.body.appendChild(modal)
    act(() => { fireEvent.dragEnter(window, { dataTransfer: fileDrag([pdf('a.pdf')]) }) })
    expect(screen.queryByRole('dialog', { name: 'Drop files into a bucket' })).toBeNull()
    modal.remove()
  })

  it('closes on Escape', () => {
    renderBuckets()
    act(() => { fireEvent.dragEnter(window, { dataTransfer: fileDrag([pdf('a.pdf')]) }) })
    act(() => { fireEvent.keyDown(window, { key: 'Escape' }) })
    expect(screen.queryByRole('dialog', { name: 'Drop files into a bucket' })).toBeNull()
  })

  it('tells the operator to save a webmail attachment first when it cannot be fetched', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('cors'))
    renderBuckets()
    const dt = {
      types: ['DownloadURL'], files: [], items: [],
      getData: t => (t === 'DownloadURL'
        ? 'application/pdf:invoice.pdf:https://mail.google.com/mail/u/0/?attid=0.1' : ''),
    }
    act(() => { fireEvent.dragEnter(window, { dataTransfer: dt }) })
    fireEvent.drop(screen.getByTestId('drop-payments'), { dataTransfer: dt })
    expect(await screen.findByRole('alert')).toHaveTextContent(/Download it .* first/)
    expect(api.upload).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})

describe('DocumentBuckets — editing many at once', () => {
  it('tags every selected document in one request', async () => {
    const user = userEvent.setup()
    renderBuckets()
    await user.click(screen.getByRole('checkbox', { name: 'Select all in Payments' }))
    const bar = screen.getByRole('region', { name: 'Bulk actions' })
    await user.type(within(bar).getByRole('combobox', { name: /Tag to add/ }), 'Payment Slip')
    await user.click(within(bar).getByRole('button', { name: 'Add tag' }))

    expect(api.patch).toHaveBeenCalledWith('/companies/e1/documents',
      { ids: expect.arrayContaining(['d1', 'd2']), add_tags: ['Payment Slip'] })
    expect(await screen.findAllByText('Payment Slip')).not.toHaveLength(0)
    expect(screen.getByRole('status')).toHaveTextContent('Tagged 2')
  })

  it('offers the bucket\'s suggested tags without requiring them', async () => {
    renderBuckets()
    await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Select d1.pdf' }))
    const options = [...document.querySelectorAll('.bk-bulk datalist option')].map(o => o.value)
    expect(options).toEqual(['Payment Slip'])
  })

  it('sets one description on all of them, and moves them', async () => {
    const user = userEvent.setup()
    renderBuckets()
    await user.click(screen.getByRole('checkbox', { name: 'Select all in Payments' }))
    const bar = screen.getByRole('region', { name: 'Bulk actions' })
    await user.type(within(bar).getByRole('textbox', { name: /Description for/ }), 'Q3 fees')
    await user.click(within(bar).getByRole('button', { name: 'Set' }))
    expect(api.patch).toHaveBeenLastCalledWith('/companies/e1/documents',
      { ids: expect.arrayContaining(['d1', 'd2']), title: 'Q3 fees' })

    await user.selectOptions(within(bar).getByRole('combobox', { name: /Move the selected/ }),
                             'maintenance')
    expect(api.patch).toHaveBeenLastCalledWith('/companies/e1/documents',
      { ids: expect.arrayContaining(['d1', 'd2']), bucket: 'maintenance' })
    await waitFor(() => expect(within(region('Maintenance')).getByText('d1.pdf')).toBeInTheDocument())
    // The fallback is never a destination.
    const options = within(bar).getAllByRole('option').map(o => o.textContent)
    expect(options).not.toContain('Other Documents')
  })

  it('selects a range with shift', async () => {
    const user = userEvent.setup()
    renderBuckets({ documents: [doc('d1'), doc('d2'), doc('d3'), doc('d4')] })
    await user.click(screen.getByRole('checkbox', { name: 'Select d4.pdf' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select d2.pdf' }), { shiftKey: true })
    for (const n of ['d4', 'd3', 'd2']) {
      expect(screen.getByRole('checkbox', { name: `Select ${n}.pdf` })).toBeChecked()
    }
    expect(screen.getByRole('checkbox', { name: 'Select d1.pdf' })).not.toBeChecked()
  })

  it('removes several after one confirmation', async () => {
    const user = userEvent.setup()
    renderBuckets()
    await user.click(screen.getByRole('checkbox', { name: 'Select all in Payments' }))
    await user.click(within(screen.getByRole('region', { name: 'Bulk actions' }))
      .getByRole('button', { name: /Remove/ }))
    const dialog = screen.getByRole('alertdialog', { name: 'Remove 2 documents' })
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(api.del).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('d1.pdf')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Bulk actions' })).toBeNull()
  })

  it('keeps a document whose removal failed, and says so', async () => {
    const user = userEvent.setup()
    api.del.mockImplementation(path => (path.endsWith('d1')
      ? Promise.reject(new Error('Not allowed')) : Promise.resolve({})))
    renderBuckets()
    await user.click(screen.getByRole('checkbox', { name: 'Select all in Payments' }))
    await user.click(within(screen.getByRole('region', { name: 'Bulk actions' }))
      .getByRole('button', { name: /Remove/ }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('d1.pdf: Not allowed')
    expect(screen.getByText('d1.pdf')).toBeInTheDocument()
    expect(screen.queryByText('d2.pdf')).toBeNull()
  })
})

describe('DocumentBuckets — editing one row in place (autosave)', () => {
  it('saves a description when the field is left, and only if it changed', async () => {
    const user = userEvent.setup()
    renderBuckets()
    const field = screen.getByRole('textbox', { name: 'Description of d1.pdf' })
    await user.click(field)
    await user.tab()
    expect(api.patch).not.toHaveBeenCalled()

    await user.type(field, 'Stamped copy{Enter}')
    expect(api.patch).toHaveBeenCalledWith('/companies/e1/documents',
      { ids: ['d1'], title: 'Stamped copy' })
    expect(await screen.findByText('Saved')).toBeInTheDocument()
  })

  it('puts the old description back when the save is refused', async () => {
    const user = userEvent.setup()
    api.patch.mockRejectedValueOnce(new Error('Too long'))
    renderBuckets({ documents: [doc('d1', { title: 'Original' })] })
    const field = screen.getByRole('textbox', { name: 'Description of d1.pdf' })
    await user.clear(field)
    await user.type(field, 'New{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('d1.pdf: Too long')
    expect(field).toHaveValue('Original')
  })

  it('adds and removes a tag on one document', async () => {
    const user = userEvent.setup()
    renderBuckets({ documents: [doc('d1', { tags: ['Old'] })] })
    await user.click(screen.getByRole('button', { name: 'Remove tag Old' }))
    expect(api.patch).toHaveBeenLastCalledWith('/companies/e1/documents',
      { ids: ['d1'], remove_tags: ['Old'] })

    await user.click(screen.getByRole('button', { name: 'Add a tag to d1.pdf' }))
    await user.type(screen.getByRole('combobox', { name: 'Add a tag to d1.pdf' }), 'Receipt{Enter}')
    expect(api.patch).toHaveBeenLastCalledWith('/companies/e1/documents',
      { ids: ['d1'], add_tags: ['Receipt'] })
    expect(await screen.findByText('Receipt')).toBeInTheDocument()
  })

  it('uses the person\'s route for a person', async () => {
    const user = userEvent.setup()
    renderBuckets({ ownerKind: 'person', ownerId: 'p1' })
    await user.type(screen.getByRole('textbox', { name: 'Description of d1.pdf' }), 'x{Enter}')
    expect(api.patch).toHaveBeenCalledWith('/persons/p1/documents', { ids: ['d1'], title: 'x' })
  })
})
