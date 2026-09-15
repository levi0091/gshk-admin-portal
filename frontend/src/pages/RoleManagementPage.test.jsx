import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import RoleManagementPage from './RoleManagementPage.jsx'

/**
 * WHAT A SUPER ADMIN CAN ACTUALLY GRANT.
 *
 * This screen's module list is a hand-maintained copy of what the API gates on,
 * and it has been wrong in both directions before: it was three modules long
 * while the database had six, so `nar1`, `tpsi` and `documents` could not be
 * granted through the UI at all and nobody but a Super Admin could see a NAR1
 * case. The failure mode is silent — the screen renders, the role saves, and
 * the missing grant only shows up as a colleague who cannot open a screen.
 */

const get = vi.fn()
const post = vi.fn()
const patch = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a),
         patch: (...a) => patch(...a) },
}))

const ROLES = [
  { id: 'r1', name: 'super_admin', role_permissions: [] },
  { id: 'r2', name: 'case_manager', role_permissions: [
    { module: 'companies', permission: 'read' },
    { module: 'nar1', permission: 'write' },
  ] },
]

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(ROLES)
})

const openCreate = async () => {
  const user = userEvent.setup()
  render(<RoleManagementPage />)
  await screen.findByText('case_manager')
  await user.click(screen.getByRole('button', { name: /New Role/ }))
  // Not "Create Role" — that is both the modal title and its submit button.
  await screen.findByText('Module Permissions')
  return user
}

describe('the modules a role can be granted', () => {
  it('offers exactly the five the API gates on', async () => {
    await openCreate()
    for (const label of ['Companies', 'Persons', 'NAR1 cases',
                         'Companies Registry filing', 'Audit Trail']) {
      expect(screen.getByText(label), label).toBeInTheDocument()
    }
  })

  it('does NOT offer Documents — it is not a module (migration 040)', async () => {
    // Levi 2026-09-07. It was one, with its own read/write/delete, and being
    // separate meant it could disagree with the record it describes: a role
    // granted Companies (edit) could not upload the certificate for a company
    // it was trusted to edit, and a role holding documents:delete alone could
    // remove a company's papers without being able to open the company.
    await openCreate()
    expect(screen.queryByText('Documents')).not.toBeInTheDocument()
  })

  it('offers no Delete level anywhere', async () => {
    // `delete` only ever existed on the documents module. Neither owner module
    // has one, and removing a document is a WRITE on the record it belongs to.
    await openCreate()
    expect(screen.queryByLabelText('Delete')).not.toBeInTheDocument()
    expect(screen.queryByText('Delete')).not.toBeInTheDocument()
  })

  it('says where documents went, on the modules that now carry them', async () => {
    // A Super Admin looking for a way to grant "documents" has to find the
    // answer on this screen rather than conclude the portal cannot do it.
    await openCreate()
    expect(screen.getByText(/Covers the company's documents too/))
      .toBeInTheDocument()
    expect(screen.getByText(/Covers identity documents and the person's other papers/))
      .toBeInTheDocument()
  })

  it('sends the ticked module and level, and nothing else', async () => {
    const user = await openCreate()
    await user.type(screen.getByPlaceholderText(/company_reviewer/), 'doc_filer')
    // "Edit" appears once per module that offers it, so it is scoped to the
    // Companies block rather than picked by name across the whole modal.
    const companies = screen.getByText('Companies').parentElement
    await user.click(within(companies).getByLabelText('Edit'))
    await user.click(screen.getByRole('button', { name: /Create Role/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/roles/', {
      name: 'doc_filer',
      permissions: [{ module: 'companies', permission: 'write' }],
    }))
  })
})
