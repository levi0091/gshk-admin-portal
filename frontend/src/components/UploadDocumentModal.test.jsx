import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import UploadDocumentModal from './UploadDocumentModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), upload: vi.fn() } }))
import { api } from '../lib/api.js'

const TYPES = [
  { code: 'coi', label: 'Certificate of Incorporation' },
  { code: 'id_scan', label: 'Identity Document Scan' },
]

const onClose = vi.fn()
const onUploaded = vi.fn()

function renderModal(props = {}) {
  return render(
    <UploadDocumentModal
      ownerKind="entity" ownerId="e1" ownerName="Acme Ltd"
      onClose={onClose} onUploaded={onUploaded} {...props}
    />
  )
}

const pdf = () => new File(['%PDF'], 'coi.pdf', { type: 'application/pdf' })

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(TYPES)
  api.upload.mockResolvedValue({ id: 'd1', current_version: 1 })
})

describe('UploadDocumentModal', () => {
  it('only offers types the owner can hold', async () => {
    // A Certificate of Incorporation is not a person's document. Asking the
    // server to scope the list is what stops it being offered here.
    renderModal({ ownerKind: 'person', ownerId: 'p1', ownerName: 'John Smith' })
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/documents/types?owner_type=person'))
  })

  it('asks for company types on a company profile', async () => {
    renderModal()
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/documents/types?owner_type=company'))
  })

  it('loads the document types into the picker', async () => {
    renderModal()
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Certificate of Incorporation' })).toBeInTheDocument()
    })
  })

  it('uploads to the company endpoint as multipart', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Certificate of Incorporation' })

    await user.selectOptions(screen.getByLabelText(/Document Type/), 'coi')
    await user.upload(screen.getByLabelText('Choose file'), pdf())
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    await waitFor(() => expect(api.upload).toHaveBeenCalled())
    const [path, fd] = api.upload.mock.calls[0]
    expect(path).toBe('/companies/e1/documents')
    expect(fd.get('document_type_code')).toBe('coi')
    expect(fd.get('file').name).toBe('coi.pdf')
    expect(onUploaded).toHaveBeenCalled()
  })

  it('uploads to the person endpoint when the owner is a person', async () => {
    const user = userEvent.setup()
    renderModal({ ownerKind: 'person', ownerId: 'p1', ownerName: 'John Smith' })
    await screen.findByRole('option', { name: 'Identity Document Scan' })

    await user.selectOptions(screen.getByLabelText(/Document Type/), 'id_scan')
    await user.upload(screen.getByLabelText('Choose file'), pdf())
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    await waitFor(() => {
      expect(api.upload.mock.calls[0][0]).toBe('/persons/p1/documents')
    })
  })

  it('warns that re-uploading an existing type creates a new version', async () => {
    const user = userEvent.setup()
    renderModal({ existingTypes: ['coi'] })
    await screen.findByRole('option', { name: 'Certificate of Incorporation' })

    await user.selectOptions(screen.getByLabelText(/Document Type/), 'coi')
    expect(await screen.findByText(/will be saved as a new version/)).toBeInTheDocument()
    // the CTA changes to make the versioning explicit
    expect(screen.getByRole('button', { name: 'Upload New Version' })).toBeInTheDocument()
  })

  it('requires a file and a type', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Certificate of Incorporation' })
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText('Choose a file to upload')).toBeInTheDocument()
    expect(api.upload).not.toHaveBeenCalled()
  })

  it('surfaces an upload error', async () => {
    const user = userEvent.setup()
    api.upload.mockRejectedValue(new Error('storage down'))
    renderModal()
    await screen.findByRole('option', { name: 'Certificate of Incorporation' })
    await user.selectOptions(screen.getByLabelText(/Document Type/), 'coi')
    await user.upload(screen.getByLabelText('Choose file'), pdf())
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText('storage down')).toBeInTheDocument()
    expect(onUploaded).not.toHaveBeenCalled()
  })
})
