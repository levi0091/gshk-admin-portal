// "Multiple directors must sign" — one panel per required signer (spec
// nd2-multi-signer §7, §8 frontend items 3 and 4). The backend is mocked at the
// api module, per the contract in §3.1.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import SignerPanels from './SignerPanels.jsx'
import { formatDateTime } from '../../lib/format.js'

const get = vi.fn(); const post = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn(), del: vi.fn() },
}))
// The real modal polls Resend; its own tests cover that. Here we only need to
// see WHEN it opens, in which phase, and for whom.
vi.mock('../case/VerificationDeliveryModal.jsx', () => ({
  default: ({ phase, deliveries, deliveryPath, onClose }) => (
    <div data-testid="delivery-modal" data-phase={phase} data-path={deliveryPath}>
      {(deliveries || []).map(d => <span key={d.email}>{d.email}</span>)}
      <button onClick={onClose}>Done</button>
    </div>
  ),
}))

const SENT = '2026-10-29T07:02:00+00:00'
const SIGNED = '2026-10-29T07:31:00+00:00'
const signer = (over = {}) => ({
  person_id: 'p1', name: 'Jacqueline Koh', roles: ['resolution'], role_label: 'director',
  suggested_email: 'jkoh@client.com', status: 'not_sent', email: null, sent_at: null,
  expires_at: null, signed_at: null, signature_captured: false, delivery: null, ...over,
})
const BRIAN = { person_id: 'p2', name: 'Brian Testing', roles: ['consent'],
  role_label: 'incoming director', suggested_email: 'brian@client.com' }
const state = (over = {}) => ({
  multi_signer: true, revision: 0, frozen: false, set_changed: false, required: 2, signed: 0,
  converged: false, signers: [signer(), signer(BRIAN)], ...over,
})
const DATA = { id: 'k1', case_no: 'ND2A-2026-0007', form_code: 'Nd2a', multi_signer: true }
const ALL = { write: true }

function panels(props = {}) {
  const all = {
    data: DATA, state: state(), can: ALL, respondBy: '2026-11-03', blocked: null, nextRevision: 1,
    refresh: vi.fn(() => Promise.resolve()), reload: vi.fn(() => Promise.resolve()), goTo: vi.fn(),
    ...props,
  }
  render(<SignerPanels {...all} />)
  return all
}
const panel = name => screen.getByRole('group', { name })

beforeEach(() => { vi.clearAllMocks() })

describe('one panel per signer', () => {
  it('titles each with the name and role, in the order the server gave', () => {
    panels()
    const groups = screen.getAllByRole('group')
    expect(groups).toHaveLength(2)
    expect(groups[0]).toHaveAccessibleName('Jacqueline Koh (director)')
    expect(groups[1]).toHaveAccessibleName('Brian Testing (incoming director)')
  })

  it('offers the director\'s address as a suggestion and leaves the field empty', () => {
    panels()
    const p = panel(/Jacqueline Koh/)
    expect(within(p).getByRole('button', { name: 'Add Jacqueline Koh (jkoh@client.com)' })).toBeInTheDocument()
    expect(within(p).queryByTestId('recipient-chips')).not.toBeInTheDocument()
    expect(within(p).getByLabelText('Add a recipient')).toHaveValue('')
  })

  it('says why a director with no address cannot be suggested', () => {
    panels({ state: state({ signers: [signer({ suggested_email: null })] }) })
    expect(screen.getByText(/no email address on record/)).toBeInTheDocument()
  })

  it('allows only one address per director', async () => {
    const user = userEvent.setup()
    panels()
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.type(within(p).getByLabelText('Add a recipient'), 'other@client.com{Enter}')
    expect(within(p).getByTestId('recipient-chips')).not.toHaveTextContent('other@client.com')
    expect(within(p).getByRole('alert')).toHaveTextContent(/at most 1/)
  })
})

describe('sending to one director', () => {
  it('stays disabled without a reply-by date, even with an address', async () => {
    const user = userEvent.setup()
    panels({ respondBy: '' })
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    expect(within(p).getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('stays disabled with a date but no address', () => {
    panels()
    expect(within(panel(/Jacqueline Koh/)).getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('stays disabled when the form itself is blocked, and says why once', async () => {
    const user = userEvent.setup()
    panels({ blocked: 'A company rule is breached — see the rules below.' })
    await user.click(within(panel(/Jacqueline Koh/)).getByRole('button', { name: /Add Jacqueline Koh/ }))
    expect(within(panel(/Jacqueline Koh/)).getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.getAllByText('A company rule is breached — see the rules below.')).toHaveLength(1)
  })

  it('posts {email, respond_by} to that director\'s route and opens the splash on the click', async () => {
    let finish
    post.mockImplementation(() => new Promise(r => { finish = r }))
    const user = userEvent.setup()
    const props = panels()
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))

    expect(post).toHaveBeenCalledWith('/officer-changes/k1/verification/signers/p1/send',
      { email: 'jkoh@client.com', respond_by: '2026-11-03' })
    // Opened on the CLICK, seeded with that one address, and not polling yet.
    const modal = screen.getByTestId('delivery-modal')
    expect(modal).toHaveAttribute('data-phase', 'sending')
    expect(modal).toHaveTextContent('jkoh@client.com')
    expect(modal).toHaveAttribute('data-path', '/officer-changes/k1/verification/delivery')

    finish({ deliveries: [{ email: 'jkoh@client.com', name: 'Jacqueline Koh', message_id: 'm1',
      person_id: 'p1' }], failed: [] })
    await waitFor(() => expect(screen.getByTestId('delivery-modal')).toHaveAttribute('data-phase', 'confirming'))
    // Nothing is refreshed underneath the splash: that would advance the stage behind it.
    expect(props.reload).not.toHaveBeenCalled()
    expect(props.refresh).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(props.refresh).toHaveBeenCalled())
    expect(props.reload).toHaveBeenCalled()
    expect(screen.queryByTestId('delivery-modal')).not.toBeInTheDocument()
  })

  it('refreshes straight away when the send reports no deliveries to wait for', async () => {
    post.mockResolvedValue({ deliveries: [], failed: [] })
    const user = userEvent.setup()
    const props = panels()
    const p = panel(/Brian Testing/)
    await user.click(within(p).getByRole('button', { name: /Add Brian Testing/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(props.refresh).toHaveBeenCalled())
    expect(props.reload).toHaveBeenCalled()
    expect(screen.queryByTestId('delivery-modal')).not.toBeInTheDocument()
  })

  it('locks the other panels while one send is in flight', async () => {
    post.mockImplementation(() => new Promise(() => {}))
    const user = userEvent.setup()
    panels()
    await user.click(within(panel(/Jacqueline Koh/)).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(panel(/Brian Testing/)).getByRole('button', { name: /Add Brian Testing/ }))
    await user.click(within(panel(/Jacqueline Koh/)).getByRole('button', { name: 'Send' }))
    expect(within(panel(/Brian Testing/)).getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('names an address the send could not mail, without claiming success', async () => {
    post.mockResolvedValue({ deliveries: [], failed: [{ email: 'jkoh@client.com', reason: 'bounced' }] })
    const user = userEvent.setup()
    panels()
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    expect(await within(p).findByText(/Not sent to: jkoh@client\.com \(bounced\)/)).toBeInTheDocument()
  })
})

describe('a refused send is shown on the panel it belongs to', () => {
  it('shows 409 address_in_use clearly on that director\'s panel and takes the splash down', async () => {
    const message = 'jkoh@client.com is already the address Brian Testing signs from. A drawn '
      + 'signature is personal, so each director needs an address of their own.'
    post.mockRejectedValue(Object.assign(new Error(message), {
      detail: { message, reason: 'address_in_use' }, reason: 'address_in_use', status: 409,
    }))
    const user = userEvent.setup()
    panels()
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    const alert = await within(p).findByRole('alert')
    expect(alert).toHaveTextContent(/already the address Brian Testing signs from/)
    expect(alert).toHaveTextContent(/each director needs an address of their own/)
    expect(within(panel(/Brian Testing/)).queryByText(/signs from/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('delivery-modal')).not.toBeInTheDocument()
    // The address is kept, so the operator can swap it rather than start over.
    expect(within(p).getByTestId('recipient-chips')).toHaveTextContent('jkoh@client.com')
  })

  it('clears the message when the operator tries again', async () => {
    post.mockRejectedValueOnce(Object.assign(new Error('Nope'), { status: 409 }))
    post.mockResolvedValueOnce({ deliveries: [], failed: [] })
    const user = userEvent.setup()
    panels()
    const p = panel(/Jacqueline Koh/)
    await user.click(within(p).getByRole('button', { name: /Add Jacqueline Koh/ }))
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    expect(await within(p).findByRole('alert')).toHaveTextContent('Nope')
    await user.click(within(p).getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(within(p).queryByText('Nope')).not.toBeInTheDocument())
  })
})

describe('each status', () => {
  const one = over => panels({ state: state({ signers: [signer(over)] }) })

  it('not_sent', () => {
    one({})
    expect(screen.getByText('Not sent')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('sent: when, and who we are waiting on; the button is Re-send', () => {
    one({ status: 'sent', email: 'jkoh@client.com', sent_at: SENT })
    expect(screen.getByText(`Sent ${formatDateTime(SENT)}, awaiting signature`)).toBeInTheDocument()
    expect(screen.getByText('Sent to jkoh@client.com')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Re-send' })).toBeInTheDocument()
  })

  it('signed: ticked, in the success style, and has no button at all', () => {
    one({ status: 'signed', email: 'jkoh@client.com', sent_at: SENT, signed_at: SIGNED, signature_captured: true })
    const line = screen.getByText(`Signed ${formatDateTime(SIGNED)} ✓`)
    expect(line).toHaveClass('is-signed')
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Add a recipient')).not.toBeInTheDocument()
  })

  it('signed, but the image was not stored: says the box will print blank', () => {
    one({ status: 'signed', signed_at: SIGNED, signature_captured: false })
    expect(screen.getByText(/signature image was not stored/i)).toBeInTheDocument()
  })

  it('expired: Re-send, in the same revision', () => {
    one({ status: 'expired', email: 'jkoh@client.com', sent_at: SENT })
    expect(screen.getByText('Link expired, not signed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Re-send' })).toBeInTheDocument()
  })

  it('not_delivered: in the warning style with Resend\'s detail, and Re-send', () => {
    one({ status: 'not_delivered', email: 'jkoh@client.com', sent_at: SENT,
      delivery: { status: 'failed', detail: 'the mailbox does not exist' } })
    const line = screen.getByText('Not delivered ✗ — the mailbox does not exist')
    expect(line).toHaveClass('is-bad')
    expect(screen.getByRole('button', { name: 'Re-send' })).toBeInTheDocument()
  })

  it('not_delivered with no detail does not print a dangling dash', () => {
    one({ status: 'not_delivered', email: 'jkoh@client.com', sent_at: SENT, delivery: null })
    expect(screen.getByText('Not delivered ✗')).toBeInTheDocument()
  })

  it('redirected: never green, never "delivered"', () => {
    one({ status: 'redirected', email: 'jkoh@client.com', sent_at: SENT,
      delivery: { status: 'redirected', detail: null } })
    const line = screen.getByText('Not sent (test)')
    expect(line).not.toHaveClass('is-signed')
    expect(screen.queryByText(/delivered/i)).not.toBeInTheDocument()
  })
})

describe('hints', () => {
  it('before the first send, says the first send fixes the form as the next revision', () => {
    panels({ nextRevision: 3 })
    expect(screen.getByText('The first send fixes the form as Rev. 3; every director receives the same copy.'))
      .toBeInTheDocument()
  })

  it('once the round is open, no longer says it', () => {
    panels({ state: state({ frozen: true, revision: 1 }) })
    expect(screen.queryByText(/The first send fixes the form/)).not.toBeInTheDocument()
  })

  it('on a Re-send, says it retires only that director\'s earlier link', () => {
    panels({ state: state({ frozen: true, revision: 1, signers: [
      signer({ status: 'sent', email: 'jkoh@client.com', sent_at: SENT }), signer(BRIAN)] }) })
    expect(within(panel(/Jacqueline Koh/)).getByText("Re-sending retires only Jacqueline Koh's earlier link."))
      .toBeInTheDocument()
    expect(within(panel(/Brian Testing/)).queryByText(/Re-sending retires/)).not.toBeInTheDocument()
  })

  it('warns when the board has changed since the form was sent', () => {
    panels({ state: state({ frozen: true, set_changed: true }) })
    expect(screen.getByText('The board has changed since this form was sent. Restart verification to ask the current directors.'))
      .toBeInTheDocument()
  })

  it('does not warn otherwise', () => {
    panels()
    expect(screen.queryByText(/The board has changed/)).not.toBeInTheDocument()
  })
})

describe('the footer', () => {
  it('counts the signatures and says the case waits for all', () => {
    panels({ state: state({ signed: 1, frozen: true }) })
    expect(screen.getByText('Signatures: 1 of 2 — case waits for all')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Continue to Data Verification/ })).not.toBeInTheDocument()
  })

  it('once converged, says so and offers Continue', async () => {
    const user = userEvent.setup()
    const props = panels({ state: state({ signed: 2, converged: true, frozen: true, signers: [
      signer({ status: 'signed', signed_at: SIGNED, signature_captured: true }),
      signer({ ...BRIAN, status: 'signed', signed_at: SIGNED, signature_captured: true })] }) })
    expect(screen.getByText('All 2 directors have signed')).toBeInTheDocument()
    expect(screen.queryByText(/case waits for all/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Continue to Data Verification →' }))
    expect(props.goTo).toHaveBeenCalledWith(2)
  })
})

describe('a role that may not write', () => {
  it('sees every director\'s status and no controls', () => {
    panels({ can: { write: false }, state: state({ signers: [
      signer({ status: 'sent', email: 'jkoh@client.com', sent_at: SENT }), signer(BRIAN)] }) })
    expect(screen.getByText(`Sent ${formatDateTime(SENT)}, awaiting signature`)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Add a recipient')).not.toBeInTheDocument()
  })
})

describe('loading', () => {
  it('says so while the signers have not arrived', () => {
    panels({ state: null })
    expect(screen.getByText(/Loading the directors/)).toBeInTheDocument()
  })

  it('says so, with a retry, when they could not be loaded', async () => {
    const user = userEvent.setup()
    const props = panels({ state: null, loadError: true })
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(props.refresh).toHaveBeenCalled()
  })
})
