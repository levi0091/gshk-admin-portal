import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import {
  DeleteRecordModal, DeletedBanner, DeletedTable, RecordGone,
} from './SoftDelete.jsx'

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}))
import { api } from '../lib/api.js'

const inRouter = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

const CAN = { can_delete: true, links: [], cases: [] }
const BLOCKED = {
  can_delete: false,
  links: [{ company_id: 'c9', company_name: 'CLIENT LTD', br_number: '123',
            roles: ['Director', 'Shareholder'] }],
  cases: [{ case_id: 'k1', case_no: 'NAR-2026-0007', workflow_status: 'awaiting_client' }],
}

function modal(props = {}) {
  const onDeleted = vi.fn()
  const onClose = vi.fn()
  inRouter(
    <DeleteRecordModal kind="company" basePath="/companies/e1"
                       name="Payward Limited"
                       identifiers={['BRN 74159213', 'Created 19 Sep 2026']}
                       onClose={onClose} onDeleted={onDeleted} {...props} />)
  return { onDeleted, onClose }
}

beforeEach(() => vi.clearAllMocks())

describe('DeleteRecordModal', () => {
  it('names the record by what tells it apart, not just by name', async () => {
    api.get.mockResolvedValue(CAN)
    modal()
    // Two Payward profiles share a name AND a BR number; the date is what
    // tells them apart.
    expect(screen.getByText('Payward Limited')).toBeInTheDocument()
    expect(screen.getByText('BRN 74159213')).toBeInTheDocument()
    expect(screen.getByText('Created 19 Sep 2026')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/companies/e1/deletion-check')
  })

  it('says what stands in the way, and offers no Delete button at all', async () => {
    api.get.mockResolvedValue(BLOCKED)
    modal()
    await screen.findByText(/cannot be deleted yet/)
    expect(screen.getByRole('link', { name: 'CLIENT LTD' }))
      .toHaveAttribute('href', '/companies/c9')
    expect(screen.getByText(/Director, Shareholder/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'NAR-2026-0007' }))
      .toHaveAttribute('href', '/cases/k1')
    expect(screen.queryByRole('button', { name: /Delete company/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Why is this company being deleted/)).not.toBeInTheDocument()
  })

  it('needs a reason before it will delete, and sends it trimmed', async () => {
    api.get.mockResolvedValue(CAN)
    api.post.mockResolvedValue({})
    const user = userEvent.setup()
    const { onDeleted } = modal()

    const button = await screen.findByRole('button', { name: 'Delete company' })
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText(/Why is this company being deleted/),
                    '  duplicate profile  ')
    expect(button).toBeEnabled()
    await user.click(button)

    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/companies/e1/delete',
                                          { reason: 'duplicate profile' })
  })

  it('on a 409, shows the refusal and asks again what blocks it', async () => {
    api.get.mockResolvedValueOnce(CAN).mockResolvedValueOnce(BLOCKED)
    api.post.mockRejectedValue(Object.assign(
      new Error('Cannot delete: it is still a current officer of CLIENT LTD'),
      { status: 409 }))
    const user = userEvent.setup()
    const { onDeleted } = modal()

    await user.type(await screen.findByLabelText(/Why is this company/), 'x')
    await user.click(screen.getByRole('button', { name: 'Delete company' }))

    await screen.findByText(/cannot be deleted yet/)
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('speaks of a person when it is one', async () => {
    api.get.mockResolvedValue(CAN)
    modal({ kind: 'person', basePath: '/persons/p1', name: 'Chan Tai Man' })
    expect(await screen.findByRole('button', { name: 'Delete person' })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/persons/p1/deletion-check')
  })
})

describe('DeletedBanner', () => {
  const RECORD = { deleted_at: '2026-09-20T02:00:00Z', deleted_by_name: 'Levi Z.',
                   deleted_reason: 'duplicate of the ETL profile' }

  it('says who deleted it, when, and why', () => {
    render(<DeletedBanner kind="company" record={RECORD} basePath="/companies/e1"
                          canRestore onRestored={vi.fn()} />)
    expect(screen.getByText('This company has been deleted.')).toBeInTheDocument()
    expect(screen.getByText(/by Levi Z\./)).toBeInTheDocument()
    expect(screen.getByText('duplicate of the ETL profile')).toBeInTheDocument()
  })

  it('restores, then lets the page re-read', async () => {
    api.post.mockResolvedValue({})
    const onRestored = vi.fn()
    const user = userEvent.setup()
    render(<DeletedBanner kind="person" record={RECORD} basePath="/persons/p1"
                          canRestore onRestored={onRestored} />)
    await user.click(screen.getByRole('button', { name: 'Restore person' }))
    await waitFor(() => expect(onRestored).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/persons/p1/restore', {})
  })

  it('offers no Restore to a role that cannot', () => {
    render(<DeletedBanner kind="company" record={RECORD} basePath="/companies/e1"
                          canRestore={false} onRestored={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /Restore/ })).not.toBeInTheDocument()
  })
})

describe('RecordGone', () => {
  it('does not say which of the two it is, and gives the way back', () => {
    inRouter(<RecordGone kind="company" backTo="/registry" backLabel="Back to Company Registry" />)
    expect(screen.getByText(/does not exist, or it has been deleted/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Company Registry' }))
      .toHaveAttribute('href', '/registry')
  })
})

describe('DeletedTable', () => {
  it('lists who deleted what and why, and opens the record', async () => {
    api.get.mockResolvedValue({
      companies: [{ id: 'e1', company_name: 'Payward Limited', br_number: '74159213',
                    deleted_at: '2026-09-20T02:00:00Z', deleted_by_name: 'Levi Z.',
                    deleted_reason: 'duplicate' }],
      total: 1,
    })
    const onOpen = vi.fn()
    const user = userEvent.setup()
    render(<DeletedTable endpoint="/companies/deleted" rowsKey="companies"
                         search="pay" refLabel="BRN" refOf={c => c.br_number}
                         onOpen={onOpen} />)
    await user.click(await screen.findByText('Payward Limited'))
    expect(onOpen).toHaveBeenCalledWith('e1')
    expect(screen.getByText('duplicate')).toBeInTheDocument()
    expect(screen.getByText('Levi Z.')).toBeInTheDocument()
    const url = api.get.mock.calls[0][0]
    expect(url.startsWith('/companies/deleted?')).toBe(true)
    expect(new URL(url, 'http://x').searchParams.get('search')).toBe('pay')
  })

  it('says so when nothing has been deleted', async () => {
    api.get.mockResolvedValue({ persons: [], total: 0 })
    render(<DeletedTable endpoint="/persons/deleted" rowsKey="persons"
                         search="" refLabel="Email" refOf={p => p.email} onOpen={vi.fn()} />)
    expect(await screen.findByText('Nothing has been deleted.')).toBeInTheDocument()
  })
})
