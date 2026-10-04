import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import EServiceCredentialCard from './EServiceCredentialCard.jsx'

const get = vi.fn(); const put = vi.fn(); const del = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: { get: (...a) => get(...a), put: (...a) => put(...a), del: (...a) => del(...a) },
}))

const STORED = { configured: true, eservice_user_id: 'ER123456', eservice_person_name: 'HO New',
  has_password: true, updated_at: '2026-09-30T02:00:00Z' }
const NONE = { configured: false, eservice_user_id: null, eservice_person_name: null,
  has_password: false, updated_at: null }

beforeEach(() => vi.clearAllMocks())

describe('EServiceCredentialCard', () => {
  it('says the username and password here are what PIN-signs the consent (Levi 2026-10-05)', async () => {
    get.mockResolvedValue(STORED)
    render(<EServiceCredentialCard personId="p9" canEdit />)
    expect(await screen.findByText(/username and password entered here are what G-FlowDesk uses to PIN-sign/)).toBeInTheDocument()
    expect(screen.getByText(/NAR1 is PIN-signed the same way, with GSHK/)).toBeInTheDocument()
    expect(screen.getByText(/filed on the CR portal instead/)).toBeInTheDocument()
  })

  it('shows the account and whether a password is stored — never the password', async () => {
    get.mockResolvedValue(STORED)
    render(<EServiceCredentialCard personId="p9" canEdit />)
    expect(await screen.findByText('ER123456')).toBeInTheDocument()
    expect(screen.getByText('Password stored')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/persons/p9/eservice-credential')
    expect(screen.getByText(/PIN-sign this person.s consent to act on an ND2A/)).toBeInTheDocument()
  })

  it('is read-only without persons:write — no Edit, no Remove, not even disabled', async () => {
    get.mockResolvedValue(STORED)
    render(<EServiceCredentialCard personId="p9" canEdit={false} />)
    await screen.findByText('ER123456')
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  })

  it('needs a password the first time, and saves the account', async () => {
    get.mockResolvedValue(NONE)
    put.mockResolvedValue({ ...STORED })
    const user = userEvent.setup()
    render(<EServiceCredentialCard personId="p9" canEdit />)
    expect(await screen.findByText(/No e-Registry account stored/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add account' }))
    await user.type(screen.getByLabelText(/e-Registry user ID/), 'ER123456')
    await user.type(screen.getByLabelText(/Name on the account/), 'HO New')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await user.type(screen.getByLabelText(/^Password/), 's3cret')
    expect(screen.getByLabelText(/^Password/)).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/persons/p9/eservice-credential', {
      eservice_user_id: 'ER123456', eservice_person_name: 'HO New', password: 's3cret' }))
    expect(await screen.findByText('Password stored')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('s3cret')).not.toBeInTheDocument()
  })

  it('keeps the stored password when the field is left blank', async () => {
    get.mockResolvedValue(STORED)
    put.mockResolvedValue({ ...STORED, eservice_user_id: 'ER999' })
    const user = userEvent.setup()
    render(<EServiceCredentialCard personId="p9" canEdit />)
    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    expect(screen.getByLabelText(/^Password/)).toHaveValue('')
    expect(screen.getByPlaceholderText(/keep the stored password/)).toBeInTheDocument()
    const id = screen.getByLabelText(/e-Registry user ID/)
    await user.clear(id); await user.type(id, 'ER999')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/persons/p9/eservice-credential', {
      eservice_user_id: 'ER999', eservice_person_name: 'HO New' }))
  })

  it('asks before removing, and says what removing costs', async () => {
    get.mockResolvedValue(STORED)
    del.mockResolvedValue({ removed: true, ...NONE })
    const user = userEvent.setup()
    render(<EServiceCredentialCard personId="p9" canEdit />)
    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/can only be filed by wet ink/)
    expect(del).not.toHaveBeenCalled()
    await user.click(screen.getAllByRole('button', { name: 'Remove' }).at(-1))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/persons/p9/eservice-credential'))
    expect(await screen.findByText(/No e-Registry account stored/)).toBeInTheDocument()
  })

  it('names the field the API refused, not the value', async () => {
    get.mockResolvedValue(NONE)
    put.mockRejectedValue(Object.assign(new Error('Enter the e-Registry user ID'), { status: 400 }))
    const user = userEvent.setup()
    render(<EServiceCredentialCard personId="p9" canEdit />)
    await user.click(await screen.findByRole('button', { name: 'Add account' }))
    await user.type(screen.getByLabelText(/e-Registry user ID/), ' x')
    await user.type(screen.getByLabelText(/Name on the account/), 'HO')
    await user.type(screen.getByLabelText(/^Password/), 'p')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the e-Registry user ID')
  })
})

describe('EServiceCredentialCard — the identity document behind the account (Jacqueline note 1)', () => {
  it('saves the document the account was opened with', async () => {
    get.mockResolvedValue({ ...STORED })
    put.mockResolvedValue({ ...STORED, registered_id_type: 'passport', registered_id_number: 'X1234567' })
    const user = userEvent.setup()
    render(<EServiceCredentialCard personId="p9" canEdit />)
    await screen.findByText('ER123456')
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.selectOptions(screen.getByLabelText(/Opened with/), 'passport')
    await user.type(screen.getByLabelText(/Document number/), 'X1234567')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][1]).toMatchObject({ registered_id_type: 'passport',
      registered_id_number: 'X1234567' })
  })

  it('warns when the profile no longer holds that document', async () => {
    get.mockResolvedValue({ ...STORED, registered_id_type: 'passport', registered_id_number: 'X1234567',
      registered_id_mismatch: "HO New's e-Registry account was opened with passport X123…; the profile now holds passport Y765…." })
    render(<EServiceCredentialCard personId="p9" canEdit />)
    expect(await screen.findByRole('alert')).toHaveTextContent('opened with passport X123')
  })
})
