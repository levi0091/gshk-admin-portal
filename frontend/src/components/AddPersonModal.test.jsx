import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AddPersonModal from './AddPersonModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { post: vi.fn(), get: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'
import { _resetDocumentSections } from '../lib/documentSections.js'

const onClose = vi.fn()
const onCreated = vi.fn()
const renderModal = () => render(<AddPersonModal onClose={onClose} onCreated={onCreated} />)

const LOOKUPS = { gender: [], nationality: [], marital_status: [], cr_country: [
  { code: 'GB', label: 'United Kingdom' }, { code: 'HK', label: 'Hong Kong' },
] }

// Which fields each identity type carries is the SERVER's answer — an HKID has
// no issuing country as far as CR is concerned, and does not expire.
const SECTIONS = {
  sections: [{
    key: 'identity', label: 'Identity Documents', is_identity: true,
    description: '', file_required: false,
    types: [
      { code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
      { code: 'id_passport', label: 'Passport', id_type: 'passport' },
    ],
  }],
  identity_fields: {
    hkid: { fields: ['id_number'], required: ['id_number'] },
    passport: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number', 'issuing_country'],
    },
  },
}

//: A real, internally consistent HKID — the check digit is computed.
const GOOD_HKID = 'A123456(3)'

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetDocumentSections()
  api.get.mockImplementation(url =>
    Promise.resolve(url.startsWith('/documents/sections') ? SECTIONS : LOOKUPS))
  api.post.mockResolvedValue({ id: 'p-1', full_name: 'Chan Tai Man' })
})

describe('AddPersonModal — discard guard (UAT F-1)', () => {
  it('closes straight away when nothing has been entered', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.click(container.querySelector('.overlay'))
    expect(onClose).toHaveBeenCalled()
    expect(screen.queryByText('Discard changes?')).not.toBeInTheDocument()
  })

  it('asks before discarding a filled form dismissed by backdrop click', async () => {
    const user = userEvent.setup()
    const { container } = renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(container.querySelector('.overlay'))
    expect(await screen.findByText('Discard changes?')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('keeps the entered data when the operator chooses Keep editing', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(await screen.findByRole('button', { name: 'Keep editing' }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Full Name/)).toHaveValue('Chan Tai Man')
  })

  it('closes when the operator confirms Discard', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('AddPersonModal — required legend (UAT F-4)', () => {
  it('explains what the asterisk means', () => {
    renderModal()
    expect(screen.getByText(/Fields marked with an asterisk are required/)).toBeInTheDocument()
  })
})

/**
 * Levi 2026-09-04: "the personal information has no field to enter the ID
 * number. can you check what other fields are missing".
 *
 * A person could be created with names, a nationality and a date of birth, and
 * no way to record the number CR files them by — the profile could only EDIT
 * identity documents, so a person created here had none and no screen offered
 * to add one.
 */
describe('AddPersonModal — the fields that were missing', () => {
  it('offers the CR name and nationality fields the profile already had', async () => {
    renderModal()
    // prevNameEng / prevNameChi are CR fields on both NAR1 and NNC1; these
    // three were editable on the profile and absent here, so each could only
    // ever be filled in on a second visit.
    expect(screen.getByLabelText('Previous Names (English)')).toBeInTheDocument()
    expect(screen.getByLabelText('Previous Names (Chinese)')).toBeInTheDocument()
    expect(screen.getByLabelText('Nationality Origin')).toBeInTheDocument()
    expect(screen.getByLabelText('Place of Birth')).toBeInTheDocument()
  })

  it('does NOT ask for an identity document', async () => {
    // Levi 2026-09-04, reversing the block added earlier the same day: "there
    // is no need for document type selection in add person action since we are
    // able to upload the documents in identity documents already". Creating a
    // person now does one thing.
    renderModal()
    expect(screen.queryByLabelText('Document Type')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/ID Number/)).not.toBeInTheDocument()
  })

  it('says where the ID number IS recorded, so nobody hunts for it here', async () => {
    renderModal()
    expect(screen.getByText(/under Identity Documents/)).toBeInTheDocument()
  })

  it('posts only the person', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.type(screen.getByLabelText('Previous Names (English)'), 'Chan Tai')
    await user.click(screen.getByRole('button', { name: 'Create Person' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/persons', {
      full_name: 'Chan Tai Man', former_name: 'Chan Tai',
    }))
  })
})
