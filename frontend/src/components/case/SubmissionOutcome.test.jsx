/**
 * Stage 4 after the 2026-10-26 incident: a submit is CLAIMED, answered 202, and
 * filed in the background — and a submit with no answer from CR is an unknown
 * outcome, never a refusal.
 *
 * On PROD the screen said "The Companies Registry refused the submission" for
 * 16 submits that had merely timed out, while CR had filed most of them; the
 * operators did what a refusal invites, and CR received the same return two
 * and three times. These tests are the screen's half of making that
 * impossible: nothing here may read a lost answer as a refusal, and nothing may
 * offer to submit a return CR may already hold.
 */
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import StageSubmission from './StageSubmission.jsx'

const get = vi.fn(); const post = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn(),
    blob: vi.fn(() => Promise.resolve(new Blob(['%PDF']))), upload: vi.fn(),
    put: vi.fn(),
  },
}))

const onChanged = vi.fn()
const onError = vi.fn()

const PREVIEW = {
  fee: '105.00', on_time_fee: '105.00', max_fee: '3480.00', fee_is_certain: true,
  balance: '12480', sufficient: true, too_early: false,
}
const PREFILL = {
  fields: { brNo: '2100028', engCoyName: 'Harbour Tech Ltd.', accNo: 'N00577470008' },
  deposit_payment_method: 'Deduct from Account',
  vocabulary: {
    pymtMtd: [{ code: 'Deduct from Account', label: 'Deduct from Account' }],
    revCode: [{ code: '16', label: '16 — Registration of annual return' }],
    docShtFrm: [{ code: 'NAR1L', label: 'NAR1L — delivered late' }],
  },
}

let FILING = { form_status: { code: 'submitting' } }

const CASE = {
  id: 'c1', case_no: 'NAR-2026-0319', filing_id: 'f1', signing_method: 'esign',
  company_name: 'Harbour Tech Ltd.', br_number: '2100028',
}
const at = (code, over = {}) => ({
  ...CASE, form_status: { code, locked: code !== 'signed' }, ...over,
})

function renderAt(code, over = {}, props = {}) {
  return render(
    <StageSubmission caseRow={at(code, over)} canSubmit
                     onChanged={onChanged} onError={onError} {...props} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  FILING = { form_status: { code: 'submitting' } }
  get.mockImplementation(url => {
    const u = String(url)
    if (u.endsWith('/preview')) return Promise.resolve(PREVIEW)
    if (u.endsWith('/summary')) return Promise.resolve({ directors: [] })
    if (u.includes('/manual-receipt-prefill')) return Promise.resolve(PREFILL)
    if (u === '/tpsi/filings/f1') return Promise.resolve(FILING)
    return Promise.resolve({})
  })
  post.mockResolvedValue({ filing_id: 'f1', stage: 'submitting' })
})

afterEach(() => {
  vi.useRealTimers()
})

const submitButton = () => screen.queryByRole('button',
  { name: /Submit NAR1 to Companies Registry/ })

async function pressSubmit(user) {
  await screen.findByText(/Fee HK\$ 105/)
  await user.click(screen.getByRole('button', { name: /I understand this submits NAR1/ }))
  await user.click(submitButton())
}

const pollsOf = () => get.mock.calls.filter(([u]) => u === '/tpsi/filings/f1').length

// --------------------------------------------------------------------------- #
//  202 — the filing is with CR; the screen waits, and says how long
// --------------------------------------------------------------------------- #

describe('a submit that has been claimed', () => {
  it('switches to the filing-in-progress state on 202 and polls every 3 s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderAt('signed')
    await pressSubmit(user)

    expect(await screen.findByText(/Filing with the Companies Registry/)).toBeInTheDocument()
    expect(screen.getByText(/up to three minutes/)).toBeInTheDocument()
    expect(screen.getByText(/Do not submit again/)).toBeInTheDocument()
    expect(submitButton()).not.toBeInTheDocument()
    expect(onError).not.toHaveBeenCalledWith(expect.anything())

    await act(() => vi.advanceTimersByTimeAsync(3000))
    expect(pollsOf()).toBe(1)
    await act(() => vi.advanceTimersByTimeAsync(3000))
    expect(pollsOf()).toBe(2)
    expect(onChanged).not.toHaveBeenCalled()

    FILING = { form_status: { code: 'submitted' } }
    await act(() => vi.advanceTimersByTimeAsync(3000))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
  })

  it('a failed status check is not a failed filing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderAt('submitting')
    get.mockImplementation(url => url === '/tpsi/filings/f1'
      ? Promise.reject(Object.assign(new Error('Could not reach the server'),
                                     { offline: true }))
      : Promise.resolve({}))

    await act(() => vi.advanceTimersByTimeAsync(3000))
    expect(await screen.findByText(/status check did not get through/)).toBeInTheDocument()
    expect(screen.getByText(/Filing with the Companies Registry/)).toBeInTheDocument()
    expect(screen.queryByText(/refused/i)).not.toBeInTheDocument()
    expect(onError).not.toHaveBeenCalled()
    expect(onChanged).not.toHaveBeenCalled()

    // And it keeps asking — no time limit turns into a failure message.
    await act(() => vi.advanceTimersByTimeAsync(3000 * 80))
    expect(pollsOf()).toBeGreaterThan(60)
    expect(screen.getByText(/Filing with the Companies Registry/)).toBeInTheDocument()
  })

  it('a page opened while the filing is in flight shows it and polls', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderAt('submitting')

    expect(screen.getByText(/Filing with the Companies Registry/)).toBeInTheDocument()
    expect(submitButton()).not.toBeInTheDocument()
    // No pre-flight: there is nothing to file, so nothing to price.
    expect(get).not.toHaveBeenCalledWith('/tpsi/filings/f1/preview')

    FILING = { form_status: { code: 'submission_unknown' } }
    await act(() => vi.advanceTimersByTimeAsync(3000))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('a POST that never got an answer reloads the case instead of saying CR refused it', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(
      new Error('Could not reach the server. Check your connection'), { offline: true }))
    renderAt('signed')
    await pressSubmit(user)

    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(onError).not.toHaveBeenCalledWith(expect.anything())
    expect(screen.queryByText(/refused/i)).not.toBeInTheDocument()
  })

  // CODE REVIEW 01, S-6. After the claim commits, a 500 or a Cloudflare 502
  // during a Railway restart is just as unknowable as a 524 -- and
  // `describeError`'s 502 branch says "nothing was filed", which the screen
  // cannot know. Only a 4xx our API answered with a body is a refusal.
  it.each([500, 502, 503, 520, 522])(
    'a %i after the claim is not a refusal either', async status => {
      const user = userEvent.setup()
      post.mockRejectedValue(Object.assign(new Error('Bad Gateway'), { status }))
      renderAt('signed')
      await pressSubmit(user)

      await waitFor(() => expect(onChanged).toHaveBeenCalled())
      expect(onError).not.toHaveBeenCalledWith(expect.anything())
    })

  it.each(['already_filing', 'filing_locked'])(
    'a 409 %s means somebody else has the filing: reload, do not keep the old card',
    async reason => {
      const user = userEvent.setup()
      post.mockRejectedValue(Object.assign(new Error('already being filed'),
                                           { status: 409, reason }))
      renderAt('signed')
      await pressSubmit(user)

      await waitFor(() => expect(onChanged).toHaveBeenCalled())
      expect(onError).not.toHaveBeenCalledWith(expect.anything())
    })

  it('the edge giving up (524) is treated the same way', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error(''), { status: 524 }))
    renderAt('signed')
    await pressSubmit(user)

    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(onError).not.toHaveBeenCalledWith(expect.anything())
  })

  it('a gate refusal before the claim is still drawn as one', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error('explicit confirmation is required'),
                                         { status: 409 }))
    renderAt('signed')
    await pressSubmit(user)

    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'explicit confirmation is required' })))
    expect(onChanged).not.toHaveBeenCalled()
  })
})

// --------------------------------------------------------------------------- #
//  submission_unknown — CR may have it
// --------------------------------------------------------------------------- #

describe('an unknown outcome', () => {
  it('says CR may have filed and charged, and never that CR refused it', () => {
    renderAt('submission_unknown')

    expect(screen.getByText(/We did not hear back from the Companies Registry/)).toBeInTheDocument()
    expect(screen.getByText(/CR may have filed this return and charged the deposit account/))
      .toBeInTheDocument()
    expect(screen.getByText(/Enquire Submitted Documents/)).toBeInTheDocument()
    expect(screen.queryByText(/refused/i)).not.toBeInTheDocument()
    expect(submitButton()).not.toBeInTheDocument()
  })

  it('offers both answers to someone with tpsi:submit', () => {
    renderAt('submission_unknown')
    expect(screen.getByRole('button', { name: /CR has it — record the receipt/ }))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /CR does not have it/ })).toBeInTheDocument()
  })

  it('renders neither answer without tpsi:submit — not merely disabled', () => {
    renderAt('submission_unknown', {}, { canSubmit: false })
    expect(screen.queryByRole('button', { name: /CR has it/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /CR does not have it/ })).not.toBeInTheDocument()
    expect(screen.getByText(/tpsi:submit/)).toBeInTheDocument()
  })

  // CODE REVIEW 01, B1.3. While a call could still be with CR the backend
  // refuses "not lodged" with a 409, so the screen withholds the control.
  it('withholds "CR does not have it" while a call may still be with CR', () => {
    const until = new Date(Date.now() + 5 * 60 * 1000).toISOString()
    renderAt('submission_unknown', { not_lodged_after: until })

    expect(screen.queryByRole('button', { name: /CR does not have it/ }))
      .not.toBeInTheDocument()
    expect(screen.getByText(/may still be with CR until \d\d:\d\d HKT/))
      .toBeInTheDocument()
    // The other answer is safe early: recording a receipt cannot cause a charge.
    expect(screen.getByRole('button', { name: /CR has it — record the receipt/ }))
      .toBeInTheDocument()
  })

  it('offers "CR does not have it" once that time has passed', () => {
    const past = new Date(Date.now() - 60 * 1000).toISOString()
    renderAt('submission_unknown', { not_lodged_after: past })
    expect(screen.getByRole('button', { name: /CR does not have it/ })).toBeInTheDocument()
  })

  it('offers it when there is no claim time at all (a repaired legacy row)', () => {
    renderAt('submission_unknown', { not_lodged_after: null })
    expect(screen.getByRole('button', { name: /CR does not have it/ })).toBeInTheDocument()
  })

  it('"CR does not have it" needs the tick before it can be declared', async () => {
    const user = userEvent.setup()
    post.mockResolvedValue({ stage: 'submission_failed', submitted_today: false })
    renderAt('submission_unknown', { submit_started_at: '2026-01-05T02:00:00+00:00' })
    await user.click(screen.getByRole('button', { name: /CR does not have it/ }))

    const declare = screen.getByRole('button', { name: /Declare it not lodged/ })
    expect(declare).toBeDisabled()
    await user.click(declare)
    expect(post).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button',
      { name: /I checked CR e-Services and this return is not listed/ }))
    expect(declare).not.toBeDisabled()
    await user.click(declare)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/tpsi/filings/f1/resolve', { outcome: 'not_lodged', checked_cr: true }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('warns that a return submitted today may not be listed yet', async () => {
    const user = userEvent.setup()
    renderAt('submission_unknown', { submit_started_at: new Date().toISOString() })
    await user.click(screen.getByRole('button', { name: /CR does not have it/ }))

    expect(screen.getByText(/submitted today/)).toBeInTheDocument()
    expect(screen.getByText(/safe choice is to wait/)).toBeInTheDocument()
  })

  it('does not warn about a return submitted on an earlier day', async () => {
    const user = userEvent.setup()
    renderAt('submission_unknown', { submit_started_at: '2026-01-05T02:00:00+00:00' })
    await user.click(screen.getByRole('button', { name: /CR does not have it/ }))

    expect(screen.queryByText(/safe choice is to wait/)).not.toBeInTheDocument()
  })

  it('"CR has it" records the receipt in CR\'s own shapes', async () => {
    const user = userEvent.setup()
    post.mockResolvedValue({ stage: 'submitted' })
    renderAt('submission_unknown')
    await user.click(screen.getByRole('button', { name: /CR has it — record the receipt/ }))

    // The derived half comes from the case, as on the off-portal form.
    expect(await screen.findByText('2100028')).toBeInTheDocument()
    await user.type(screen.getByLabelText('CR Case number'), '180256934')
    await user.type(screen.getByLabelText('Payment number'), '5010475972')
    await user.type(screen.getByLabelText('Payment reference'), '733037536')
    fireEvent.change(screen.getByLabelText('Transaction date'), { target: { value: '2026-10-23' } })
    fireEvent.change(screen.getByLabelText('Transaction time'), { target: { value: '09:15:30' } })
    await user.selectOptions(screen.getByLabelText('Payment method'), 'Deduct from Account')
    await user.type(screen.getByLabelText('Total amount'), '2610')
    await user.type(screen.getByLabelText('Receipt no.'), 'D7700')
    await user.selectOptions(screen.getByLabelText('Revenue code'), '16')
    await user.selectOptions(screen.getByLabelText('Document code'), 'NAR1L')
    await user.type(screen.getByLabelText('Amount charged'), '2610')
    // Paid from the deposit account, so the account is filled in for it.
    expect(screen.getByText('N00577470008')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Record CR's receipt/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/tpsi/filings/f1/resolve', {
      outcome: 'lodged',
      receipt: {
        caseNo: '180256934', pymtNo: '5010475972', pymtRefNo: '733037536',
        transactionDate: '23/10/2026', transactionTime: '09:15:30',
        pymtMtd: 'Deduct from Account', totalAmount: '2610.00',
        paymentRcptList: [{ rcptNo: 'D7700', revCode: '16', docShtFrm: 'NAR1L',
                            amtChrg: '2610.00' }],
      },
    }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('lists every problem with the receipt beside the form', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error('the receipt is incomplete'), {
      status: 400, problems: ['pymtNo: required', 'transactionTime: required'] }))
    renderAt('submission_unknown')
    await user.click(screen.getByRole('button', { name: /CR has it — record the receipt/ }))
    await user.type(await screen.findByLabelText('CR Case number'), '1')
    fireEvent.change(screen.getByLabelText('Transaction date'), { target: { value: '2026-10-23' } })
    await user.type(screen.getByLabelText('Total amount'), '1')
    await user.click(screen.getByRole('button', { name: /Record CR's receipt/ }))

    expect(await screen.findByText('pymtNo: required')).toBeInTheDocument()
    expect(screen.getByText('transactionTime: required')).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalledWith(expect.anything())
  })

  it('hands a CR verification refusal to the page banner', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(
      new Error('CR does not recognise case number 1'), { status: 422 }))
    renderAt('submission_unknown')
    await user.click(screen.getByRole('button', { name: /CR has it — record the receipt/ }))
    await user.type(await screen.findByLabelText('CR Case number'), '1')
    fireEvent.change(screen.getByLabelText('Transaction date'), { target: { value: '2026-10-23' } })
    await user.type(screen.getByLabelText('Total amount'), '1')
    await user.click(screen.getByRole('button', { name: /Record CR's receipt/ }))

    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'CR does not recognise case number 1' })))
    expect(onChanged).not.toHaveBeenCalled()
  })
})
