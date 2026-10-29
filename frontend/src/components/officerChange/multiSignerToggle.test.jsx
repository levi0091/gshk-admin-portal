// The "Multiple directors must sign" option on the ND2 Client Verification
// stage (spec nd2-multi-signer §7, §8 frontend items 1-3). With it off the
// stage is today's screen — clientVerification.test.jsx pins that, unedited.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import StageClientVerification from './StageClientVerification.jsx'

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: vi.fn(), upload: vi.fn(), put: vi.fn(), blob: vi.fn(() => Promise.resolve(new Blob(['%PDF']))),
  },
}))
vi.mock('../case/PdfPreview.jsx', () => ({
  default: () => <div data-testid="pdf" />,
  usePdfBlob: () => ({ url: null, error: null }),
}))
vi.mock('../case/VerificationDeliveryModal.jsx', () => ({
  default: ({ phase, deliveries }) => (
    <div data-testid="delivery-modal" data-phase={phase}>
      {(deliveries || []).map(d => <span key={d.email}>{d.email}</span>)}
    </div>
  ),
}))

const ALL = { write: true }
const READ = { write: false }
const BASE = {
  id: 'k1', case_no: 'ND2A-2026-0007', form_code: 'Nd2a', case_type: 'ND2A', editable: true,
  entries: [{ id: 'n1', kind: 'cessation', party: { name: 'CHAN Tai Man' }, summary: 'Director' }],
  documents: [], rules: { blocking: false, lines: [], board: { directors: [{ name: 'A' }], secretaries: [] }, checks: [] },
  problems: [], reply_by_default: '2026-11-03', client_approved: null, multi_signer: false,
  verification_revision: 0,
}
const signer = (over = {}) => ({
  person_id: 'p1', name: 'Jacqueline Koh', roles: ['resolution'], role_label: 'director',
  suggested_email: 'jkoh@client.com', status: 'not_sent', email: null, sent_at: null, expires_at: null,
  signed_at: null, signature_captured: false, delivery: null, ...over,
})
const SIGNERS = (over = {}) => ({
  multi_signer: false, revision: 0, frozen: false, set_changed: false, required: 2, signed: 0,
  converged: false,
  signers: [signer(), signer({ person_id: 'p2', name: 'Brian Testing', role_label: 'incoming director',
    suggested_email: 'brian@client.com' })],
  ...over,
})

let signersReply
function route(url) {
  if (url.endsWith('/verification/signers')) return signersReply()
  if (url.endsWith('/verification/recipients')) return Promise.resolve({ recipients: [], default_to: [] })
  return Promise.resolve({})
}
const wrap = (data, can = ALL, extra = {}) => render(
  <MemoryRouter>
    <StageClientVerification data={{ ...BASE, ...data }} reload={extra.reload || vi.fn()} can={can}
                             goTo={extra.goTo || vi.fn()} />
  </MemoryRouter>)
const option = () => screen.queryByRole('checkbox', { name: 'Multiple directors must sign' })

beforeEach(() => {
  vi.clearAllMocks()
  signersReply = () => Promise.resolve(SIGNERS())
  get.mockImplementation(route)
})

describe('the option', () => {
  it('is shown unchecked, and checking it patches {multi_signer: true}', async () => {
    patch.mockResolvedValue({ ...BASE, multi_signer: true })
    const reload = vi.fn()
    const user = userEvent.setup()
    wrap({}, ALL, { reload })
    await waitFor(() => expect(option()).toBeEnabled())
    expect(option()).not.toBeChecked()
    await user.click(option())
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1', { multi_signer: true })
    await waitFor(() => expect(reload).toHaveBeenCalled())
  })

  it('unchecking it patches {multi_signer: false}', async () => {
    patch.mockResolvedValue({ ...BASE })
    const user = userEvent.setup()
    wrap({ multi_signer: true })
    await waitFor(() => expect(option()).toBeEnabled())
    expect(option()).toBeChecked()
    await user.click(option())
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1', { multi_signer: false })
  })

  it('says how many directors would sign', async () => {
    wrap({})
    expect(await screen.findByText(/2 directors/)).toBeInTheDocument()
  })

  it('is disabled once the form has been sent, with the restart hint', async () => {
    wrap({ verification_sent_at: '2026-10-29T07:00:00Z', verification_revision: 1 })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/officer-changes/k1/verification/signers'))
    expect(option()).toBeDisabled()
    expect(screen.getByText('Restart verification to change this.')).toBeInTheDocument()
  })

  it('is disabled when no director has a box to sign, and says why', async () => {
    signersReply = () => Promise.resolve(SIGNERS({ required: 0, signers: [] }))
    wrap({})
    expect(await screen.findByText('No director on this form has a box to sign.')).toBeInTheDocument()
    expect(option()).toBeDisabled()
  })

  it('can still be switched OFF when the count has fallen to zero', async () => {
    signersReply = () => Promise.resolve(SIGNERS({ multi_signer: true, required: 0, signers: [] }))
    wrap({ multi_signer: true })
    await waitFor(() => expect(get).toHaveBeenCalledWith('/officer-changes/k1/verification/signers'))
    await waitFor(() => expect(option()).toBeEnabled())
  })

  it('is absent for a read-only user while it is off', async () => {
    wrap({}, READ)
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(option()).not.toBeInTheDocument()
  })

  it('is shown but cannot be changed by a read-only user when it is on', async () => {
    wrap({ multi_signer: true }, READ)
    expect(await screen.findByRole('checkbox', { name: 'Multiple directors must sign' })).toBeDisabled()
  })

  it('shows a refused change in the stage\'s own banner', async () => {
    patch.mockRejectedValue(Object.assign(new Error('The form has been sent.'), { status: 409 }))
    const user = userEvent.setup()
    wrap({})
    await waitFor(() => expect(option()).toBeEnabled())
    await user.click(option())
    expect(await screen.findByText('The form has been sent.')).toBeInTheDocument()
  })

  it('still works if the signers cannot be fetched (the toggle is simply not told a count)', async () => {
    signersReply = () => Promise.reject(new Error('down'))
    wrap({})
    await waitFor(() => expect(option()).toBeEnabled())
  })
})

describe('option off — today\'s screen', () => {
  it('keeps the recipient picker, the single send and "Client approved"', async () => {
    wrap({ verification_sent_at: '2026-10-29T07:00:00Z' })
    expect(screen.getByRole('button', { name: 'Client approved' })).toBeInTheDocument()
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
  })

  it('has the single "Send to client" and no panels', async () => {
    wrap({})
    expect(await screen.findByRole('button', { name: 'Send to client' })).toBeInTheDocument()
    expect(screen.queryByRole('group')).not.toBeInTheDocument()
  })
})

describe('option on', () => {
  const on = (over = {}) => wrap({ multi_signer: true, ...over })

  it('replaces "Send to client" and "Client approved", and keeps "Client declined"', async () => {
    on({ verification_sent_at: '2026-10-29T07:00:00Z', verification_revision: 1 })
    await screen.findAllByRole('group')
    expect(screen.queryByRole('button', { name: 'Send to client' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Client approved' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Client declined' })).toBeInTheDocument()
  })

  it('has no "Send to client" before the first send either', async () => {
    on()
    await screen.findAllByRole('group')
    expect(screen.queryByRole('button', { name: 'Send to client' })).not.toBeInTheDocument()
    // The only pickers on screen are the panels' own: one per signer, not a third.
    expect(screen.getAllByTestId('recipient-suggestions')).toHaveLength(2)
  })

  it('draws one panel per signer, from the signers endpoint', async () => {
    on()
    const groups = await screen.findAllByRole('group')
    expect(groups).toHaveLength(2)
    expect(groups[0]).toHaveAccessibleName('Jacqueline Koh (director)')
    expect(groups[1]).toHaveAccessibleName('Brian Testing (incoming director)')
  })

  it('shows the suggestion pill with the email and the field empty', async () => {
    on()
    const p = (await screen.findAllByRole('group'))[0]
    expect(within(p).getByRole('button', { name: 'Add Jacqueline Koh (jkoh@client.com)' })).toBeInTheDocument()
    expect(within(p).getByLabelText('Add a recipient')).toHaveValue('')
    expect(within(p).queryByTestId('recipient-chips')).not.toBeInTheDocument()
  })

  it('has one shared Reply-by field, defaulted from the case', async () => {
    on()
    await screen.findAllByRole('group')
    const fields = screen.getAllByLabelText(/Reply by/)
    expect(fields).toHaveLength(1)
    expect(fields[0]).toHaveValue('2026-11-03')
  })

  it('Send is disabled until there is an address and a Reply-by date', async () => {
    const user = userEvent.setup()
    on()
    const p = (await screen.findAllByRole('group'))[0]
    expect(within(p).getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    expect(within(p).getByRole('button', { name: 'Send' })).toBeEnabled()
    await user.clear(screen.getByLabelText(/Reply by/))
    expect(within(p).getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('Send posts {email, respond_by} for that director and opens the delivery modal with the address', async () => {
    post.mockResolvedValue({ deliveries: [{ email: 'brian@client.com', name: 'Brian Testing',
      person_id: 'p2' }], failed: [] })
    const user = userEvent.setup()
    on()
    const p = (await screen.findAllByRole('group'))[1]
    await user.click(within(p).getByRole('button', { name: /Add Brian Testing/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/verification/signers/p2/send',
      { email: 'brian@client.com', respond_by: '2026-11-03' })
    const modal = await screen.findByTestId('delivery-modal')
    expect(modal).toHaveTextContent('brian@client.com')
  })

  it('a date the operator picks is the one every director is sent', async () => {
    post.mockResolvedValue({ deliveries: [], failed: [] })
    const user = userEvent.setup()
    on()
    const p = (await screen.findAllByRole('group'))[0]
    const date = screen.getByLabelText(/Reply by/)
    await user.clear(date)
    await user.type(date, '2026-11-10')
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    expect(post).toHaveBeenCalledWith(expect.any(String), { email: 'jkoh@client.com', respond_by: '2026-11-10' })
  })

  it('refetches the signers when the revision, the answer or the option changes', async () => {
    const { rerender } = wrap({ multi_signer: true })
    await screen.findAllByRole('group')
    const count = () => get.mock.calls.filter(([u]) => u.endsWith('/verification/signers')).length
    const before = count()
    const next = patchData => rerender(
      <MemoryRouter>
        <StageClientVerification data={{ ...BASE, multi_signer: true, ...patchData }}
                                 reload={vi.fn()} can={ALL} goTo={vi.fn()} />
      </MemoryRouter>)
    next({ verification_revision: 1 })
    await waitFor(() => expect(count()).toBe(before + 1))
    next({ verification_revision: 1, client_approved: true })
    await waitFor(() => expect(count()).toBe(before + 2))
    next({ verification_revision: 1, client_approved: true, multi_signer: false })
    await waitFor(() => expect(count()).toBe(before + 3))
  })

  it('does not show the stage-level Continue twice once converged', async () => {
    signersReply = () => Promise.resolve(SIGNERS({ multi_signer: true, converged: true, signed: 2, frozen: true }))
    on({ client_approved: true, verification_sent_at: '2026-10-29T07:00:00Z', verification_revision: 1 })
    await screen.findAllByRole('group')
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Continue to Data Verification →' })).toHaveLength(1))
  })

  it('an ND2B waiver still lets the case continue before the directors have signed', async () => {
    signersReply = () => Promise.resolve(SIGNERS({ multi_signer: true, converged: false, signed: 0, frozen: true }))
    on({ form_code: 'Nd2b', case_type: 'ND2B', client_approved: true,
      client_approval: { source: 'staff_waiver', reason: 'away' },
      verification_sent_at: '2026-10-29T07:00:00Z', verification_revision: 1 })
    await screen.findAllByRole('group')
    expect(screen.getAllByRole('button', { name: 'Continue to Data Verification →' })).toHaveLength(1)
  })

  it('offers "Proceed without confirmation" on an ND2B, as before', async () => {
    on({ form_code: 'Nd2b', case_type: 'ND2B', verification_sent_at: '2026-10-29T07:00:00Z',
      verification_revision: 1 })
    await screen.findAllByRole('group')
    expect(screen.getByRole('button', { name: 'Proceed without confirmation' })).toBeInTheDocument()
  })
})
