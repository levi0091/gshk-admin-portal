import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CloseCaseModal from './CloseCaseModal.jsx'

const post = vi.fn()
vi.mock('../../lib/api.js', () => ({ api: { post: (...a) => post(...a) } }))

const CASE = {
  id: 'c1', case_no: 'NAR-2026-0041', company_name: 'Harbour Tech Ltd.',
}

let onClose, onClosed

beforeEach(() => {
  vi.clearAllMocks()
  post.mockResolvedValue({})
  onClose = vi.fn()
  onClosed = vi.fn()
})

function open(caseRow = CASE) {
  render(<CloseCaseModal caseRow={caseRow} onClose={onClose} onClosed={onClosed} />)
}

const reasonBox = () => screen.getByLabelText(/Why is this case not proceeding/)
const confirmBox = () => screen.getByLabelText(/to confirm/)
const confirmBtn = () => screen.getByRole('button', { name: /Close case permanently/ })

// --------------------------------------------------------------------------- #
//  What it says before anything is pressed
// --------------------------------------------------------------------------- #

describe('CloseCaseModal — the warning', () => {
  it('names the case and the company being closed', () => {
    // A workflow screen is reached from a list, and closing the case above the
    // one you meant is the mistake with no remedy.
    open()
    // Twice, on purpose: once in the warning and once in the label asking for
    // it back, so the number being typed is the number being closed.
    expect(screen.getAllByText('NAR-2026-0041')).toHaveLength(2)
    expect(screen.getByText(/Harbour Tech Ltd\./)).toBeInTheDocument()
  })

  it('says plainly that it cannot be undone, and what stops working', () => {
    open()
    expect(screen.getByText('This cannot be undone.')).toBeInTheDocument()
    expect(screen.getByText(/cannot be reopened/)).toBeInTheDocument()
    expect(screen.getByText(/no annual return will be filed/)).toBeInTheDocument()
    // The outstanding Confirm links are the consequence an operator will not
    // think of on their own, and a director pressing a dead link is how they
    // would otherwise find out.
    expect(screen.getByText(/confirmation link already sent/)).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- #
//  The two things it asks for
// --------------------------------------------------------------------------- #

describe('CloseCaseModal — the guard', () => {
  it('starts disabled', () => {
    open()
    expect(confirmBtn()).toBeDisabled()
  })

  it('is not satisfied by a reason alone', async () => {
    const user = userEvent.setup()
    open()
    await user.type(reasonBox(), 'client is dissolving the company')
    expect(confirmBtn()).toBeDisabled()
  })

  it('is not satisfied by the case number alone', async () => {
    const user = userEvent.setup()
    open()
    await user.type(confirmBox(), 'NAR-2026-0041')
    expect(confirmBtn()).toBeDisabled()
  })

  it('rejects whitespace as a reason', async () => {
    const user = userEvent.setup()
    open()
    await user.type(reasonBox(), '    ')
    await user.type(confirmBox(), 'NAR-2026-0041')
    expect(confirmBtn()).toBeDisabled()
  })

  it('rejects a NEARBY case number', async () => {
    // The whole point: 0040 and 0041 sit next to each other in the list.
    const user = userEvent.setup()
    open()
    await user.type(reasonBox(), 'stopped')
    await user.type(confirmBox(), 'NAR-2026-0040')
    expect(confirmBtn()).toBeDisabled()
  })

  it('accepts the number in any case, with stray spaces', async () => {
    // The check is against absent-mindedness, not against typing.
    const user = userEvent.setup()
    open()
    await user.type(reasonBox(), 'stopped')
    await user.type(confirmBox(), '  nar-2026-0041 ')
    expect(confirmBtn()).toBeEnabled()
  })

  it('asks only for a reason when the case has no number', async () => {
    // Rare — the number is allocated at creation — but a confirmation nobody
    // can satisfy is worse than one that leans on the reason alone.
    const user = userEvent.setup()
    open({ ...CASE, case_no: null })
    expect(screen.queryByLabelText(/to confirm/)).toBeNull()
    await user.type(reasonBox(), 'stopped')
    expect(confirmBtn()).toBeEnabled()
  })
})

// --------------------------------------------------------------------------- #
//  What it sends, and what it does with the answer
// --------------------------------------------------------------------------- #

describe('CloseCaseModal — the request', () => {
  async function fill(user, reason = 'client is dissolving the company') {
    await user.type(reasonBox(), reason)
    await user.type(confirmBox(), 'NAR-2026-0041')
  }

  it('posts the trimmed reason to this case', async () => {
    const user = userEvent.setup()
    open()
    await fill(user, '  client is dissolving the company  ')
    await user.click(confirmBtn())
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/close', { reason: 'client is dissolving the company' }))
  })

  it('hands back to the page rather than declaring success itself', async () => {
    // The page re-reads the case. The backend derives the badge from two
    // records, and guessing the new one here is how a screen starts disagreeing
    // with the trail it shares.
    const user = userEvent.setup()
    open()
    await fill(user)
    await user.click(confirmBtn())
    await waitFor(() => expect(onClosed).toHaveBeenCalled())
  })

  it('does not post twice when the button is pressed twice', async () => {
    // There is no undo, so a double-click must not become two closures — and
    // the second would 409 on the race guard anyway, showing a refusal for a
    // close that in fact worked.
    const user = userEvent.setup()
    let release
    post.mockImplementationOnce(() => new Promise(r => { release = r }))
    open()
    await fill(user)
    // Held once, because the label becomes "Closing…" on the first press —
    // which is itself the signal that a second press is not wanted.
    const button = confirmBtn()
    await user.click(button)
    await user.click(button)
    expect(post).toHaveBeenCalledTimes(1)
    expect(button).toBeDisabled()
    release({})
  })

  it('shows a refusal in the dialog and lets the operator try again', async () => {
    const user = userEvent.setup()
    open()
    await fill(user)
    post.mockRejectedValueOnce(Object.assign(
      new Error('the Companies Registry already holds this return'),
      { status: 409, reason: 'case_filed' }))
    await user.click(confirmBtn())

    const dialog = screen.getByRole('alertdialog', { name: 'Close case' })
    await within(dialog).findByText(/already holds this return/)
    expect(onClosed).not.toHaveBeenCalled()
    expect(confirmBtn()).toBeEnabled()
  })

  it('cannot be dismissed mid-flight', async () => {
    // Clicking the backdrop while the close is in the air would leave the
    // operator on a workflow screen that is about to stop being one.
    const user = userEvent.setup()
    let release
    post.mockImplementationOnce(() => new Promise(r => { release = r }))
    open()
    await fill(user)
    await user.click(confirmBtn())

    // Both ways out: the footer button and the × in the header.
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button',
                                      { name: 'Cancel and keep this case open' }))
    expect(onClose).not.toHaveBeenCalled()
    release({})
  })
})
