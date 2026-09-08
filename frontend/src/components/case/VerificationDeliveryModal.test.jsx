import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import VerificationDeliveryModal, { TIMEOUT_MS } from './VerificationDeliveryModal.jsx'

const get = vi.fn()
vi.mock('../../lib/api.js', () => ({ api: { get: (...a) => get(...a) } }))

const DELIVERIES = [
  { email: 'chan@example.com', name: 'CHAN', message_id: 'm1' },
  { email: 'lee@example.com', name: 'LEE', message_id: 'm2' },
]

function renderIt(onClose = vi.fn()) {
  render(<VerificationDeliveryModal caseId="c1" deliveries={DELIVERIES}
                                    onClose={onClose} />)
  return onClose
}

/** One settled answer: both delivered. */
const ALL_GOOD = {
  sent_at: 'x', settled: true, delivered: 2, failed: 0, pending: 0,
  recipients: [
    { email: 'chan@example.com', name: 'CHAN', status: 'delivered', detail: null },
    { email: 'lee@example.com', name: 'LEE', status: 'delivered', detail: null },
  ],
}

describe('VerificationDeliveryModal', () => {
  beforeEach(() => { get.mockReset() })
  afterEach(() => { vi.useRealTimers() })

  it('lists every director the moment it opens, before any answer', () => {
    // Seeded from the send response rather than appearing a poll later — the
    // operator must see WHO is being confirmed straight away.
    get.mockReturnValue(new Promise(() => {}))   // never resolves
    renderIt()
    expect(screen.getByText('chan@example.com', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('lee@example.com', { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText('Sending…').length).toBeGreaterThan(0)
  })

  it('holds the operator until Resend has reported', async () => {
    // The actual ask: "wait for the resend to confirm the status of each email
    // that is sent before allowing user to proceed with something else".
    get.mockReturnValue(new Promise(() => {}))
    renderIt()
    const done = screen.getByRole('button')
    expect(done).toBeDisabled()
    expect(screen.getByRole('alertdialog')).toHaveAttribute('aria-busy', 'true')
  })

  it('releases the operator once every message has settled', async () => {
    get.mockResolvedValue(ALL_GOOD)
    const onClose = renderIt()
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(screen.getAllByText('Delivered')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('NAMES the director who did not get it, and why', async () => {
    // Named, never counted: an operator who reads "1 of 2 failed" and not WHICH
    // one cannot re-send to the right person.
    get.mockResolvedValue({
      sent_at: 'x', settled: true, delivered: 1, failed: 1, pending: 0,
      recipients: [
        { email: 'chan@example.com', name: 'CHAN', status: 'delivered', detail: null },
        { email: 'lee@example.com', name: 'LEE', status: 'failed',
          detail: "the recipient's mail server rejected it" },
      ],
    })
    renderIt()
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(screen.getByText(/One director did not get it/)).toBeInTheDocument()
    expect(screen.getByText(/lee@example\.com\./)).toBeInTheDocument()
    expect(screen.getByText(/mail server rejected it/)).toBeInTheDocument()
    // And it warns what pressing Send again costs — every approval link on the
    // case is reissued, so directors who already answered are asked again.
    expect(screen.getByText(/reissues every approval link/)).toBeInTheDocument()
  })

  it('keeps polling while one message is still in flight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    get.mockResolvedValueOnce({
      sent_at: 'x', settled: false, delivered: 1, failed: 0, pending: 1,
      recipients: [
        { email: 'chan@example.com', name: 'CHAN', status: 'delivered', detail: null },
        { email: 'lee@example.com', name: 'LEE', status: 'pending', detail: null },
      ],
    }).mockResolvedValue(ALL_GOOD)

    renderIt()
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1))
    // Still holding — one director unresolved is not a finished send.
    expect(screen.getByRole('button')).toBeDisabled()
    await vi.advanceTimersByTimeAsync(3100)
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(get.mock.calls.length).toBeGreaterThan(1)
  })

  it('stops waiting at the timeout and does NOT call it a failure', async () => {
    // Delivery confirmation has no upper bound. A screen that blocked until
    // certainty could hold a case worker indefinitely — so it stops, says who
    // is unresolved, and is explicit that this is not a failure.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    get.mockResolvedValue({
      sent_at: 'x', settled: false, delivered: 1, failed: 0, pending: 1,
      recipients: [
        { email: 'chan@example.com', name: 'CHAN', status: 'delivered', detail: null },
        { email: 'lee@example.com', name: 'LEE', status: 'pending', detail: null },
      ],
    })
    renderIt()
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS + 4000)
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(screen.getByText(/Still waiting on lee@example\.com/)).toBeInTheDocument()
    expect(screen.getByText(/this is not a failure/)).toBeInTheDocument()
    expect(screen.queryByText(/did not get it/)).not.toBeInTheDocument()
  })

  it('a failed POLL is not a failed delivery', async () => {
    // The check being unavailable says nothing about whether the mail arrived.
    // Turning that into a red row against a director would send someone
    // chasing a re-send of a letter that landed.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    get.mockRejectedValue(new Error('network down'))
    renderIt()
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS + 4000)
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(screen.getByText(/could not be checked just now/)).toBeInTheDocument()
    expect(screen.getByText(/emails were still sent/)).toBeInTheDocument()
    expect(screen.queryByText(/did not get it/)).not.toBeInTheDocument()
  })

  it('stops polling once unmounted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    get.mockResolvedValue({ sent_at: 'x', settled: false, pending: 2, failed: 0,
                            delivered: 0, recipients: [] })
    const { unmount } = render(
      <VerificationDeliveryModal caseId="c1" deliveries={DELIVERIES}
                                 onClose={vi.fn()} />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    unmount()
    const after = get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(get.mock.calls.length).toBe(after)
  })
})
