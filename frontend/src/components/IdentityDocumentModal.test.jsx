import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import IdentityDocumentModal from './IdentityDocumentModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { upload: vi.fn() } }))
import { api } from '../lib/api.js'

const TYPES = [
  { code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
  { code: 'id_passport', label: 'Passport', id_type: 'passport' },
]

const IDENTITY_FIELDS = {
  hkid: { fields: ['id_number'], required: ['id_number'] },
  passport: {
    fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
    required: ['id_number', 'issuing_country'],
  },
}

const LOOKUPS = { cr_country: [{ code: 'GB', label: 'United Kingdom' }] }

//: Internally consistent — the check digit is computed, so a made-up number
//: here would make every validation assertion meaningless.
const GOOD_HKID = 'A123456(3)'

const onClose = vi.fn()
const onSaved = vi.fn()

function renderModal(props = {}) {
  return render(
    <IdentityDocumentModal
      personId="p1" personName="John Smith" types={TYPES}
      identityFields={IDENTITY_FIELDS} lookups={LOOKUPS}
      onClose={onClose} onSaved={onSaved} {...props}
    />
  )
}

const pdf = () => new File(['%PDF'], 'passport.pdf', { type: 'application/pdf' })

const pick = async (user, code) =>
  user.selectOptions(screen.getByLabelText(/Document Type/), code)

beforeEach(() => {
  vi.clearAllMocks()
  api.upload.mockResolvedValue({ id: 'i1', id_type: 'passport' })
})

describe('IdentityDocumentModal', () => {
  it('shows only the fields the chosen type carries', async () => {
    // CR has no country box beside <hkid> and a Hong Kong identity card does
    // not expire; offering three more fields invites answers CR cannot use.
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_hkid')
    expect(screen.getByLabelText(/^ID Number/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Issuing Country/)).not.toBeInTheDocument()

    await pick(user, 'id_passport')
    expect(screen.getByLabelText(/Issuing Country/)).toBeInTheDocument()
    expect(screen.getByLabelText('Expiry Date')).toBeInTheDocument()
  })

  it('records the number with no scan at all', async () => {
    // GSHK holds passport numbers whose scan nobody can find, and CR never asks
    // to see one. Refusing the number until a file turns up would block a
    // return over evidence the Registry does not want.
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_passport')
    await user.type(screen.getByLabelText(/^ID Number/), '987654321')
    await user.selectOptions(screen.getByLabelText(/Issuing Country/), 'GB')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.upload).toHaveBeenCalled())
    const [path, fd] = api.upload.mock.calls[0]
    expect(path).toBe('/persons/p1/identity-documents')
    expect(fd.get('id_type')).toBe('passport')
    expect(fd.get('id_number')).toBe('987654321')
    expect(fd.get('issuing_country')).toBe('GB')
    expect(fd.get('file')).toBeNull()
    expect(onSaved).toHaveBeenCalled()
  })

  it('sends the scan alongside the number when one is attached', async () => {
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_passport')
    await user.type(screen.getByLabelText(/^ID Number/), '987654321')
    await user.selectOptions(screen.getByLabelText(/Issuing Country/), 'GB')
    await user.upload(screen.getByLabelText('Choose file'), pdf())
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.upload).toHaveBeenCalled())
    expect(api.upload.mock.calls[0][1].get('file').name).toBe('passport.pdf')
  })

  it('does not send a field the chosen type does not carry', async () => {
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), GOOD_HKID)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.upload).toHaveBeenCalled())
    expect(api.upload.mock.calls[0][1].get('issuing_country')).toBeNull()
  })

  it('says which record it is about to REPLACE, and that the scan is kept', async () => {
    // The number is overwritten and the file is versioned. Those are different
    // answers to different questions and the operator has to know which is which
    // before pressing the button, not after.
    const user = userEvent.setup()
    renderModal({
      existing: [{ id: 'i1', id_type: 'passport', id_number: 'OLD-111' }],
    })

    await pick(user, 'id_passport')
    expect(screen.getByText(/Saving\s+REPLACES those details/)).toBeInTheDocument()
    expect(screen.getByText(/OLD-111/)).toBeInTheDocument()
    expect(screen.getByText(/kept as a new version/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument()
  })

  it('leaves a different type reading as an addition, not a replacement', async () => {
    const user = userEvent.setup()
    renderModal({
      existing: [{ id: 'i1', id_type: 'passport', id_number: 'OLD-111' }],
    })

    await pick(user, 'id_hkid')
    expect(screen.queryByText(/REPLACES/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('refuses an HKID whose check digit does not match', async () => {
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), 'Z351007(9)')
    expect(screen.getByText(/check digit does not match/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.upload).not.toHaveBeenCalled()
  })

  it('will not take a passport number without its issuing country', async () => {
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_passport')
    await user.type(screen.getByLabelText(/^ID Number/), '987654321')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/Issuing Country\/Region is required/)).toBeInTheDocument()
    expect(api.upload).not.toHaveBeenCalled()
  })

  it('makes the first document a person holds their primary one', async () => {
    const user = userEvent.setup()
    renderModal()

    await pick(user, 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), GOOD_HKID)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.upload).toHaveBeenCalled())
    expect(api.upload.mock.calls[0][1].get('is_primary')).toBe('true')
  })

  it('surfaces a save failure without closing', async () => {
    const user = userEvent.setup()
    api.upload.mockRejectedValue(new Error('storage down'))
    renderModal()

    await pick(user, 'id_hkid')
    await user.type(screen.getByLabelText(/^ID Number/), GOOD_HKID)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('storage down')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })
})
