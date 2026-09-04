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

  it('offers an identity document, with the types the server names', async () => {
    renderModal()
    expect(await screen.findByRole('option', { name: 'Passport' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Hong Kong Identity Card' })).toBeInTheDocument()
  })

  it('shows only the fields the chosen type carries', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Passport' })

    // An HKID takes a number and nothing else — CR has no country box beside
    // <hkid>, and the card does not expire.
    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_hkid')
    expect(screen.getByLabelText(/^ID Number/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Issuing Country/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Expiry Date')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_passport')
    expect(screen.getByLabelText(/Issuing Country/)).toBeInTheDocument()
    expect(screen.getByLabelText('Expiry Date')).toBeInTheDocument()
  })

  it('posts the identity document alongside the person', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Passport' })

    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), GOOD_HKID)
    await user.click(screen.getByRole('button', { name: 'Create Person' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/persons', {
      full_name: 'Chan Tai Man',
      identity_document: { id_type: 'hkid', id_number: GOOD_HKID, is_primary: true },
    }))
  })

  it('creates a person with no identity document at all', async () => {
    // Optional: a person can be recorded before their documents arrive.
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.click(screen.getByRole('button', { name: 'Create Person' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/persons', { full_name: 'Chan Tai Man' }))
  })

  it('refuses an HKID whose check digit does not match', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Passport' })

    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), 'Z351007(9)')
    await user.click(screen.getByRole('button', { name: 'Create Person' }))

    expect(await screen.findByText(/check digit does not match/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('will not take a passport number without its issuing country', async () => {
    // `nar1_mapper` refuses a passport number whose issuing country has no CR
    // code, so an empty one is a filing blocked long after this screen.
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Passport' })

    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_passport')
    await user.type(screen.getByLabelText(/^ID Number/), '987654321')
    await user.click(screen.getByRole('button', { name: 'Create Person' }))

    expect(await screen.findByText(/without its issuing country/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('will not silently drop a number typed against no type', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByRole('option', { name: 'Passport' })

    await user.type(screen.getByLabelText(/Full Name/), 'Chan Tai Man')
    await user.selectOptions(screen.getByLabelText('Document Type'), 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), GOOD_HKID)
    await user.selectOptions(screen.getByLabelText('Document Type'), '')
    // Clearing the type resets the block, so nothing half-typed is submitted.
    expect(screen.queryByLabelText(/^ID Number/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Create Person' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/persons', { full_name: 'Chan Tai Man' }))
  })
})
