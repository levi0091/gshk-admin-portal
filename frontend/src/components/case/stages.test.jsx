import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import StageDataVerification from './StageDataVerification.jsx'
import StageClientVerification from './StageClientVerification.jsx'
import StageSigning from './StageSigning.jsx'
import StageSubmission from './StageSubmission.jsx'
import StageConfirmation from './StageConfirmation.jsx'

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn()
const blob = vi.fn(); const upload = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    blob: (...a) => blob(...a), upload: (...a) => upload(...a), put: vi.fn(),
  },
}))

// These stages render outside a router and outside an AuthProvider, so the
// context would otherwise be null. Reassigned per-test where the environment
// matters; production is the default so the test-environment note has to be
// asked for explicitly rather than appearing everywhere by accident.
let auth = { isTestEnv: false }
vi.mock('../../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const onChanged = vi.fn()
const onError = vi.fn()
const onWarn = vi.fn()

/** Render inside a router, for stages that link or navigate. */
const renderRouted = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

const CASE = {
  id: 'c1', entity_id: 'e7', case_no: 'NAR-2026-0041', filing_id: 'f1',
  company_name: 'Harbour Tech Ltd.', signing_method: 'esign',
  // Both manual pre-checks done. "Validate with CR" is gated on them
  // (wireframe_v11: validation stays locked until they are ticked), so a
  // fixture without them cannot reach the CR button at all — and every test
  // below that is about what validation DOES would silently pass by never
  // getting there.
  aml_cleared: true, accounts_ready: true,
  form_status: { code: 'validated', label: 'Validated by CR', failed: false, faults: [] },
}
const at = over => ({ ...CASE, ...over })

//: GET /cases/{id}/return-data — the Data Verification card reads it on every
//: render. Routed by URL rather than left to the blanket mock below, which
//: would hand the card a deposit-balance payload and render an empty return
//: that no assertion here would notice.
const RETURN_DATA = {
  year: 2026, company_name: 'Harbour Tech Ltd.', br_number: '2100028',
  registered_office: 'Unit 12A, Central, Hong Kong',
  directors: ['Chan Tai Man'], secretaries: ['Get Started HK Limited'],
  signatory: { name: 'Chan Tai Man', capacity: 'Director', person_id: 'T2607D' },
  member_count: 2,
  share_classes: [{ name: 'Ordinary', total_issued: 100, currency: 'HKD' }],
  problems: [],
}

//: GET /tpsi/filings/{id}/summary — the FROZEN return, read back out of the
//: validated XML. Deliberately a DIFFERENT company name from RETURN_DATA
//: above: the two endpoints answer different questions, and a fixture that
//: made them identical could not tell whether the Submission card had been
//: wired to the live profile by mistake.
const FILING_SUMMARY = {
  form_code: 'Nar1', stage: 'signed', has_schedule_1: true,
  company_name: 'Harbour Tech Ltd.', br_number: '2100028', year: '2026',
  registered_office: 'Unit 12A, Central, HKG',
  directors: ['CHAN, TAI MAN'], secretaries: ['Get Started HK Limited'],
  share_classes: [{ name: 'Ordinary', currency: 'HKD', total_issued: '100' }],
  member_count: 2, members: ['CHAN, TAI MAN', 'WONG, MEI LING'],
  signatory: { name: 'CHAN, TAI MAN', capacity: 'Director', date: '27/08/2026' },
  signed_at: '2026-08-27T06:00:00Z',
}

//: GET /cases/{id}/verification/recipients — the board. Three directors, one of
//: whom cannot be written to, because that is the case the send screen has to
//: get visibly right: a chip row of two for a board of three.
const RECIPIENTS = {
  recipients: [
    { person_id: 'p1', name: 'AH CHAN', email: 'chan@example.com',
      role: 'director', party_type: 'individual', reason: null },
    { person_id: 'p2', name: 'BO LEE', email: 'lee@example.com',
      role: 'director', party_type: 'individual', reason: null },
    { person_id: null, name: 'HOLDCO LIMITED', email: null, role: 'director',
      party_type: 'corporate',
      reason: 'a corporate director has no address on record' },
  ],
  company_email: 'office@example.com',
  default_to: ['chan@example.com', 'lee@example.com'],
  max_recipients: 20,
}

//: GET /tpsi/credentials — the SIGNING credential of whoever is logged in. It
//: is the only thing that can sign a NAR1 (Q1), so the Signing stage reads it
//: to say whose signature is about to be applied, and refuses without it.
//: Reassigned per-test where the absence is the point.
let CREDENTIALS = {
  eservice_user_id: 'GSHKPN02', has_eservice_password: true,
  eservice_password_hint: '••••••••9021', is_test: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { isTestEnv: false }
  CREDENTIALS = {
    eservice_user_id: 'GSHKPN02', has_eservice_password: true,
    eservice_password_hint: '••••••••9021', is_test: true,
  }
  get.mockImplementation(url => {
    const u = String(url)
    if (u.includes('/return-data')) return Promise.resolve(RETURN_DATA)
    if (u.includes('/verification/recipients')) return Promise.resolve(RECIPIENTS)
    if (u.includes('/summary')) return Promise.resolve(FILING_SUMMARY)
    if (u.includes('/tpsi/credentials')) return Promise.resolve(CREDENTIALS)
    return Promise.resolve({ fee: '105.00', max_fee: '3480.00',
                             fee_is_certain: false,
                             balance: '12480', sufficient: true })
  })
  post.mockResolvedValue({}); patch.mockResolvedValue({}); upload.mockResolvedValue({})
  blob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
  global.URL.createObjectURL = vi.fn(() => 'blob:preview')
  global.URL.revokeObjectURL = vi.fn()
})

// ---------------------------------------------------------------------------
// 1 · Data Verification
// ---------------------------------------------------------------------------

describe('Data Verification', () => {
  const renderIt = (over = {}, props = {}) => render(
    <StageDataVerification caseRow={at(over)} canWrite canValidate
                           onChanged={onChanged} onError={onError} {...props} />)

  it('records the two manual pre-checks against the case', async () => {
    const user = userEvent.setup()
    renderIt({ form_status: { code: 'draft' }, filing_id: null,
               aml_cleared: false, accounts_ready: false })
    await user.click(screen.getByRole('button', { name: /AML screening cleared/ }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/cases/c1', { aml_cleared: true }))
  })

  it('will not let CR be called until both pre-checks are ticked', async () => {
    // wireframe_v11: "CR validation stays locked until they are ticked". The
    // checks assert work done outside the portal, and a case that reaches the
    // client without them is expensive to walk back once the snapshot is
    // frozen.
    renderIt({ form_status: { code: 'draft' }, filing_id: null,
               aml_cleared: true, accounts_ready: false })
    expect(screen.getByRole('button', { name: /Validate with CR/ })).toBeDisabled()
    expect(screen.getByText(/Tick both manual checks above/)).toBeInTheDocument()
  })

  it('prepares a filing and then validates it, in that order', async () => {
    const user = userEvent.setup()
    post.mockResolvedValueOnce({ id: 'f9' })
    renderIt({ form_status: { code: 'draft' }, filing_id: null })
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    expect(post.mock.calls[0][0]).toBe('/tpsi/filings/prepare')
    expect(post.mock.calls[0][1]).toEqual({ entity_id: 'e7', nar1_case_id: 'c1' })
    expect(post.mock.calls[1][0]).toBe('/tpsi/filings/f9/validate')
  })

  it('rebuilds the return before re-validating, so a correction reaches CR', async () => {
    // THE BUG THIS REPLACES. `validate` re-sends the filing's STORED xml, and
    // this screen used to skip prepare whenever the case already had a filing.
    // So an operator who fixed an address or changed the signing capacity and
    // pressed Validate again sent CR the same bytes and read the identical
    // refusal as "my correction did nothing" — observed on NAR-2026-0065, where
    // the case said 'Company Secretary' and the stored xml still said
    // selectCapacityDesc 'Director'.
    //
    // prepare now refreshes the case's own draft in place, so this does not
    // orphan a second filing the way it once would have.
    const user = userEvent.setup()
    post.mockResolvedValueOnce({ id: 'f1' })
    renderIt({ form_status: { code: 'validation_failed', failed: true, faults: ['x'] } })
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    expect(post.mock.calls[0][0]).toBe('/tpsi/filings/prepare')
    expect(post.mock.calls[1][0]).toBe('/tpsi/filings/f1/validate')
  })

  it('does NOT rebuild a snapshot CR has already validated', async () => {
    // From `validated` onward the case reads its own frozen snapshot — the PDF
    // the client approves and the document that gets filed. Rewriting it under
    // them is exactly the "show one document, file another" failure the
    // verification gate exists to prevent; Restart verification is the way.
    const user = userEvent.setup()
    renderIt({ form_status: { code: 'validated', failed: false, faults: [] } })
    const btn = screen.queryByRole('button', { name: /Validate with CR/ })
    if (btn) {
      await user.click(btn)
      await waitFor(() => expect(post).toHaveBeenCalled())
      expect(post.mock.calls.some(c => c[0] === '/tpsi/filings/prepare')).toBe(false)
    }
  })

  it('leaves the CR faults to the page banner instead of drawing them twice', async () => {
    // ONE ERROR SURFACE (Levi 2026-08-31). The same rejection used to appear in
    // the page banner AND in this card's own FaultPanel, a screen apart, which
    // reads as two different problems. The banner is now the only place —
    // covered by persistedFailure in workflow.test.js and by the rendering
    // assertions in CaseWorkflowPage.test.jsx.
    renderIt({
      form_status: {
        code: 'validation_failed', failed: true,
        faults: ['Partial HKID is required', 'Signatory date precedes appointment'],
      },
    })
    expect(screen.queryByText('Partial HKID is required')).toBeNull()
    expect(screen.queryByText(/Nothing was charged/)).toBeNull()
  })

  it('says the snapshot is frozen once CR has validated it', () => {
    renderIt()
    expect(screen.getByText(/CR-signed snapshot frozen/)).toBeInTheDocument()
  })

  it('explains a shut CR window instead of just failing', async () => {
    // Reported UP to the page, which owns the single error banner. Asserted at
    // the boundary rather than in this card's markup, because that is where the
    // message now goes.
    const user = userEvent.setup()
    const onError = vi.fn()
    post.mockRejectedValue(Object.assign(new Error('outside the window'), { status: 503 }))
    renderIt({ form_status: { code: 'draft' }, filing_id: null }, { onError })
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ hint: expect.stringMatching(/10:00–16:00 Hong Kong time/) }),
    ))
  })

  it('points at the header for Restart rather than owning the button', () => {
    // Restart moved to the page header (Q3/v11) so it is reachable from Client
    // Verification and Signing — the stages you are on when you discover the
    // snapshot is wrong. Its behaviour is covered in CaseWorkflowPage.test.jsx.
    renderIt()
    expect(screen.queryByRole('button', { name: /Restart verification/ })).toBeNull()
    expect(screen.getByText(/at the top of the page/)).toBeInTheDocument()
  })


  it('explains that validating freezes an immutable snapshot', () => {
    renderIt({ form_status: { code: 'draft' }, filing_id: null })
    expect(screen.getByText(/freezes an immutable snapshot/)).toBeInTheDocument()
    expect(screen.getByText(/validateFormNar1/)).toBeInTheDocument()
  })

  it('names the permission validation needs, and that it is free', () => {
    renderIt({ form_status: { code: 'draft' }, filing_id: null })
    expect(screen.getByText(/validation is free/)).toBeInTheDocument()
  })

  it('offers Continue to Client Verification once the snapshot exists', async () => {
    const onGo = vi.fn()
    renderIt({}, { onGo })
    await userEvent.setup().click(
      screen.getByRole('button', { name: /Continue to Client Verification/ }))
    expect(onGo).toHaveBeenCalledWith(2)
  })
})

// ---------------------------------------------------------------------------
// 2 · Client Verification
// ---------------------------------------------------------------------------

describe('Client Verification', () => {
  const renderIt = (over = {}) => render(
    <StageClientVerification caseRow={at(over)} canWrite onWarn={onWarn}
                             onChanged={onChanged} onError={onError} />)

  // ── spec §5: one message per director, so a send can partly succeed ─────

  async function pressSend() {
    // Same gate the other send tests go through: the chips have to be on
    // screen and the review ticked before the button is live.
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('chan@example.com')
    await user.click(screen.getByRole('button', { name: /I have reviewed this return/ }))
    await user.click(screen.getByRole('button', { name: /Send to client/ }))
    return user
  }

  it('names the directors a partial send did NOT reach', async () => {
    // The case an operator is most likely to miss: the screen advances, the
    // status changes, and one director was never asked. It is raised to the
    // page, which draws it at the top and scrolls there — the stage keeps no
    // alert of its own (Levi 2026-09-03).
    post.mockResolvedValue({ sent_at: 'x', to: ['a@x.com'],
                             failed_to: ['b@x.com'], approval_links: true })
    await pressSend()
    await waitFor(() => expect(onWarn).toHaveBeenCalledWith(
      'The return did not reach everyone.',
      expect.stringMatching(/b@x\.com/)))
    expect(onWarn).toHaveBeenLastCalledWith(
      expect.any(String), expect.stringMatching(/The others have it/))
  })

  it('says nothing about a partial send when everyone got it', async () => {
    post.mockResolvedValue({ sent_at: 'x', to: ['a@x.com'], failed_to: [],
                             approval_links: true })
    await pressSend()
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    // Only the clear-down at the start of the send, never a warning.
    expect(onWarn).not.toHaveBeenCalledWith(expect.any(String), expect.any(String))
  })

  it('says when the email went out with no Confirm button', async () => {
    // Nobody should be waiting for a button press that is not in the email.
    post.mockResolvedValue({ sent_at: 'x', to: ['a@x.com'], failed_to: [],
                             approval_links: false })
    await pressSend()
    await waitFor(() => expect(onWarn).toHaveBeenCalledWith(
      'Sent without a Confirm button.',
      expect.stringMatching(/reply by email/)))
    expect(onWarn).toHaveBeenLastCalledWith(
      expect.any(String), expect.stringMatching(/PUBLIC_API_BASE_URL/))
  })

  // ── v11 restorations (Q3, Block C) ──────────────────────────────────────

  it('leads with the frozen snapshot, so a moved profile is not a mystery', () => {
    renderIt()
    expect(screen.getByText(/Snapshot frozen at validation/)).toBeInTheDocument()
    expect(screen.getByText(/not the live profile/)).toBeInTheDocument()
  })

  it('labels the preview with what it is and where it came from', async () => {
    renderIt()
    expect(await screen.findByText('Form NAR1 + Schedule 1')).toBeInTheDocument()
    expect(screen.getByText('Rendered from the CR-validated XML')).toBeInTheDocument()
    expect(screen.getByText(/NAR1_Harbour_Tech_Ltd_\.pdf/)).toBeInTheDocument()
  })

  it('zooms the preview, within bounds', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('100%')
    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByText('120%')).toBeInTheDocument()
    // Bounded: past 200% the viewport is taller than any screen.
    for (let i = 0; i < 10; i += 1) {
      await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    }
    expect(screen.getByText('200%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled()
  })

  it('downloads the return rather than only embedding it', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Download PDF/ }))
    // Two reads of the same endpoint: one for the embed, one for the save.
    await waitFor(() => expect(blob).toHaveBeenCalledTimes(2))
    expect(blob.mock.calls[1][0]).toBe('/tpsi/filings/f1/pdf')
  })

  it('gives the preview enough height to read a statutory return', async () => {
    renderIt()
    const frame = await screen.findByLabelText('NAR1 preview')
    // 690px at 100% zoom. The return is nine A4 pages and the operator is
    // checking particulars against the company record, not glancing at it.
    expect(frame).toHaveStyle({ height: '690px' })
  })

  it('opens the return full screen — even 690px cannot show a nine-page form', async () => {
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Open full screen/ }))
    expect(open).toHaveBeenCalledWith('blob:preview', '_blank', 'noopener')
    vi.unstubAllGlobals()
  })

  it('names the permission sending needs', () => {
    renderIt()
    expect(screen.getByText(/nar1:write/)).toBeInTheDocument()
  })

  it('renders the PDF from the CR-validated snapshot', async () => {
    renderIt()
    await waitFor(() => expect(blob).toHaveBeenCalledWith('/tpsi/filings/f1/pdf'))
  })

  // Levi 2026-08-30. The interlock itself is enforced in the backend
  // (email_service.TEST_RECIPIENTS); these cover only the operator being told.
  it('says nothing is really sent to the client, in a test environment', async () => {
    auth = { isTestEnv: true }
    renderIt()
    expect(await screen.findByText(/nothing is delivered to the client/i))
      .toBeInTheDocument()
  })

  it('still shows the real director addresses in a test environment', async () => {
    // The point of the note is that the picker keeps behaving normally — the
    // fan-out is the thing under test, so the chips must stay real.
    auth = { isTestEnv: true }
    renderIt()
    expect(await screen.findByText('chan@example.com')).toBeInTheDocument()
  })

  it('does NOT show that note on production', async () => {
    auth = { isTestEnv: false }
    renderIt()
    await screen.findByText('chan@example.com')
    expect(screen.queryByText(/nothing is delivered to the client/i))
      .not.toBeInTheDocument()
  })

  it('fetches the PDF as a blob so the token never lands in a URL', async () => {
    renderIt()
    await waitFor(() => expect(blob).toHaveBeenCalled())
    expect(get.mock.calls.some(c => String(c[0]).includes('/pdf'))).toBe(false)
  })

  it('revokes the object URL on unmount rather than leaking the document', async () => {
    const { unmount } = renderIt()
    await waitFor(() => expect(global.URL.createObjectURL).toHaveBeenCalled())
    unmount()
    await waitFor(() => expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview'))
  })

  it('will NOT send to the client until the return has been reviewed', async () => {
    const user = userEvent.setup()
    renderIt()
    const send = screen.getByRole('button', { name: /Send to client/ })
    expect(send).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /I have reviewed this return/ }))
    expect(screen.getByRole('button', { name: /Send to client/ })).toBeEnabled()
  })

  const reviewAndSend = async user => {
    // The chips must be on screen first — the send button is gated on them.
    await screen.findByText('chan@example.com')
    await user.click(screen.getByRole('button', { name: /I have reviewed this return/ }))
    await user.click(screen.getByRole('button', { name: /Send to client/ }))
  }

  it('seeds the recipients with every director who has an address', async () => {
    renderIt()
    await screen.findByText('chan@example.com')
    expect(screen.getByText('lee@example.com')).toBeInTheDocument()
    expect(screen.getByText('AH CHAN')).toBeInTheDocument()
  })

  // ── Levi 2026-08-30: one section, in the order the decision is made ──────

  it('puts the recipients between the review tick and the send button', async () => {
    // Not decoration. They used to be a separate card BELOW the button, so an
    // operator met the list of who was mailed only after mailing them.
    renderIt()
    await screen.findByText('chan@example.com')
    const card = screen.getByText('Send for verification').closest('.card')
    const tick = within(card).getByRole('button', { name: /I have reviewed this return/ })
    const chips = within(card).getByTestId('recipient-chips')
    const send = within(card).getByRole('button', { name: /Send to client/ })
    // DOCUMENT_POSITION_FOLLOWING === 4. Asserting order, not merely presence.
    expect(tick.compareDocumentPosition(chips) & 4).toBeTruthy()
    expect(chips.compareDocumentPosition(send) & 4).toBeTruthy()
  })

  it('names the address the copy goes to, rather than promising "you"', async () => {
    auth = { isTestEnv: false, profile: { email: 'levi@zenexflow.com' } }
    renderIt()
    await screen.findByText('chan@example.com')
    expect(screen.getByText('levi@zenexflow.com')).toBeInTheDocument()
    expect(screen.getByText(/reply comes back to you/)).toBeInTheDocument()
  })

  it('still explains the copy when the profile has no address to name', async () => {
    auth = { isTestEnv: false, profile: {} }
    renderIt()
    await screen.findByText('chan@example.com')
    expect(screen.getByText(/A copy goes to you/)).toBeInTheDocument()
  })

  // ── The failure Levi hit: a refused send that looked like a dead button ──

  it('reports a refused send to the PAGE, and draws none of its own', async () => {
    // It used to be drawn at the button, because the page banner sits above a
    // 690px PDF frame — about a screen and a half up — and a refused send
    // therefore looked like a dead button. The page now scrolls to the banner
    // on every failure, so the reason is gone; keeping it would leave this one
    // stage with an error surface no other stage has (Levi 2026-09-03).
    post.mockRejectedValueOnce(
      Object.assign(new Error('this case was completed off-portal'), { status: 409 }))
    const user = userEvent.setup()
    renderIt()
    await reviewAndSend(user)
    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        message: expect.stringMatching(/off-portal/) })))
    const card = screen.getByText('Send for verification').closest('.card')
    expect(within(card).queryByRole('alert')).toBeNull()
  })

  it('does not send the CR office-hours hint when the mail config is missing', async () => {
    // describeError's 503 hint points at CR's Mon–Fri window. Nothing on this
    // path touches CR, and waiting for Hong Kong office hours fixes nothing.
    post.mockRejectedValueOnce(
      Object.assign(new Error('RESEND_API_KEY is not set'), { status: 503 }))
    const user = userEvent.setup()
    renderIt()
    await reviewAndSend(user)
    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        hint: expect.stringMatching(/missing its email configuration/) })))
    expect(onError).not.toHaveBeenCalledWith(expect.objectContaining({
      hint: expect.stringMatching(/10:00/) }))
  })

  it('offers no send at all once the return has been filed', async () => {
    // Not a DISABLED button beside a warning — no button. A control you may
    // not press, next to a sentence explaining why, invites the press; the
    // record of what happened is what belongs on a finished case.
    renderIt({ manual_submitted_at: '2026-08-28T03:32:06Z' })
    await screen.findByText('chan@example.com')
    expect(screen.queryByRole('button', { name: /Send to client/ })).toBeNull()
  })

  it('keeps the review tick ticked once the mail has gone', async () => {
    // It gates the send, and the send is the evidence it was given: the mail
    // could not have left without it. An unticked box on a case whose banner
    // says "Sent 31 Aug 2026, 19:52" reads as a step that came undone — which
    // is exactly how it was reported, after stepping to Signing and back.
    renderIt({ verification_sent_at: '2026-08-31T11:52:00Z' })
    await screen.findByText('chan@example.com')
    const tick = screen.getByRole('button',
      { name: /I have reviewed this return and it is correct/ })
    expect(tick).toHaveAttribute('aria-pressed', 'true')
    // Nothing left for it to gate, so it stops inviting a click.
    expect(tick).toBeDisabled()
  })

  it('leaves the review tick clear on a case that was never sent', async () => {
    renderIt({ verification_sent_at: null })
    await screen.findByText('chan@example.com')
    expect(screen.getByRole('button',
      { name: /I have reviewed this return and it is correct/ }))
      .toHaveAttribute('aria-pressed', 'false')
  })

  it('shows the director it cannot write to rather than dropping them', async () => {
    // A board of three rendering two chips looks exactly like a board of two.
    renderIt()
    expect(await screen.findByText(/HOLDCO LIMITED/)).toBeInTheDocument()
    expect(screen.getByText(/no address on record/)).toBeInTheDocument()
  })

  it('sends to every seeded director, not just the first', async () => {
    const user = userEvent.setup()
    renderIt()
    await reviewAndSend(user)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/verification/send',
      { to: ['chan@example.com', 'lee@example.com'] }))
  })

  it('sends the list on screen, so a removed director is not mailed', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('chan@example.com')
    await user.click(screen.getByRole('button', { name: 'Remove chan@example.com' }))
    await user.click(screen.getByRole('button', { name: /I have reviewed this return/ }))
    await user.click(screen.getByRole('button', { name: /Send to client/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/verification/send', { to: ['lee@example.com'] }))
  })

  it('adds an extra recipient who is not on the board', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('chan@example.com')
    await user.type(screen.getByLabelText('Add a recipient'), 'levi@zenexflow.com')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    await reviewAndSend(user)
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/verification/send',
      { to: ['chan@example.com', 'lee@example.com', 'levi@zenexflow.com'] }))
  })

  it('refuses to add something that is not an address', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('chan@example.com')
    await user.type(screen.getByLabelText('Add a recipient'), 'not-an-address')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    expect(screen.getByText(/is not an email address/)).toBeInTheDocument()
  })

  it('will not send with an empty recipient list', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText('chan@example.com')
    await user.click(screen.getByRole('button', { name: /I have reviewed this return/ }))
    await user.click(screen.getByRole('button', { name: 'Remove chan@example.com' }))
    await user.click(screen.getByRole('button', { name: 'Remove lee@example.com' }))
    expect(screen.getByRole('button', { name: /Send to client/ })).toBeDisabled()
    expect(post).not.toHaveBeenCalled()
  })

  it('no longer claims a send was stubbed — mail really sends now', async () => {
    // EMAIL_TRANSPORT=console was removed on 2026-08-30, so the backend cannot
    // return this any more and the warning would be a false alarm. What the
    // operator needs to know on a test deployment is the recipient
    // substitution, which the test-environment note covers.
    const user = userEvent.setup()
    post.mockResolvedValue({ transport: 'console' })
    renderIt()
    await reviewAndSend(user)
    expect(screen.queryByText(/Nothing was actually delivered/)).toBeNull()
  })

  it('does not cry stub on a real send', async () => {
    const user = userEvent.setup()
    post.mockResolvedValue({ transport: 'resend' })
    renderIt()
    await reviewAndSend(user)
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(screen.queryByText(/Nothing was actually delivered/)).toBeNull()
  })

  it('cannot record an answer before the return was sent', () => {
    renderIt()
    expect(screen.getByRole('button', { name: /Client approved/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Client declined/ })).toBeDisabled()
  })

  it('records the client\'s yes and no as different answers', async () => {
    const user = userEvent.setup()
    renderIt({ verification_sent_at: '2026-08-01T00:00:00Z' })
    await user.click(screen.getByRole('button', { name: /Client approved/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/verification/response', { approved: true }))

    post.mockClear()
    await user.click(screen.getByRole('button', { name: /Client declined/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/verification/response', { approved: false }))
  })

  it('shows a decline as a decline, with what to do next', () => {
    renderIt({
      verification_sent_at: '2026-08-01T00:00:00Z',
      client_response_at: '2026-08-03T00:00:00Z', client_approved: false,
    })
    expect(screen.getByText('Client declined')).toBeInTheDocument()
    expect(screen.getByText(/restart verification and send it again/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 3 · Signing
// ---------------------------------------------------------------------------

describe('Signing', () => {
  // Inside a router: the no-credential path links to CR Credentials, which is
  // the whole remedy it offers, and a bare render would throw on the Link.
  const renderIt = (over = {}) => render(
    <MemoryRouter>
      <StageSigning caseRow={at(over)} canWrite onChanged={onChanged} onError={onError} />
    </MemoryRouter>)

  // ── spec §5: what authorises this signature ────────────────────────────

  it('names the director who approved, on the screen that signs the return', () => {
    renderIt({ client_approval: {
      source: 'self_service', name: 'AH CHAN', system: false,
      summary: 'Approved by AH CHAN using the link in the verification email',
      responded_at: '2026-09-02T03:00:00Z' } })
    const panel = screen.getByTestId('client-approval-provenance')
    expect(within(panel).getByText(/AH CHAN/)).toBeInTheDocument()
  })

  it('SAYS SO when nobody answered and the system approved it', () => {
    // The one that matters. A return nobody confirmed must not look, on the
    // screen that signs it, exactly like one a director agreed to.
    renderIt({ client_approval: {
      source: 'system_timeout', name: null, system: true,
      summary: 'System-approved — the client did not respond within 14 days',
      responded_at: '2026-09-02T03:00:00Z' } })
    const panel = screen.getByTestId('client-approval-provenance')
    expect(within(panel).getByText(/did not respond within 14 days/)).toBeInTheDocument()
    expect(within(panel).getByText(/check with the client before signing/))
      .toBeInTheDocument()
  })

  it('distinguishes a relayed reply from a client who pressed the button', () => {
    renderIt({ client_approval: {
      source: 'staff_relay', name: 'BO LEE', system: false,
      summary: 'Approved by BO LEE, recorded by a member of staff' } })
    expect(screen.getByText(/recorded by a member of staff/)).toBeInTheDocument()
  })

  it('shows nothing at all when there is no approval to describe', () => {
    renderIt({ client_approval: null })
    expect(screen.queryByTestId('client-approval-provenance')).not.toBeInTheDocument()
  })

  it('defaults to e-Sign — nothing switches to manual by itself', () => {
    renderIt({ signing_method: null })
    expect(screen.getByRole('radio', { name: /e-Sign/ }))
      .toHaveAttribute('aria-checked', 'true')
  })

  it('states the consequence of each method on the card itself', () => {
    // v11 draws these as cards precisely so the consequence has somewhere to
    // live. A toggle with the warning in a separate alert is what this
    // replaced, and the alert only appeared AFTER choosing.
    renderIt({ signing_method: null })
    expect(screen.getByText(/drawn from the GSHK deposit account when you submit/))
      .toBeInTheDocument()
    expect(screen.getByText(/Filed off-portal: no CR API call and no fee deducted here/))
      .toBeInTheDocument()
  })

  it('records the chosen method on the case', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('radio', { name: /Manual/ }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/cases/c1', { signing_method: 'manual' }))
  })

  it('signs as the logged-in user, sending nothing about who signs', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Apply signature/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/tpsi/filings/f1/sign', {}))
  })

  it('offers no way to sign as somebody else (Q1)', async () => {
    renderIt()
    await screen.findByText(/CR e-Service account/)
    // The two boxes that used to be here are the whole point of the change:
    // who signs is the session's, not a field on a form.
    expect(screen.queryByLabelText(/Signatory e-Service user ID/)).toBeNull()
    expect(screen.queryByLabelText(/e-Service signing password/)).toBeNull()
  })

  it('names the account whose signature will be applied', async () => {
    renderIt()
    expect(await screen.findByText('GSHKPN02')).toBeInTheDocument()
  })

  it('refuses to sign when the user has no stored signing password', async () => {
    CREDENTIALS = { eservice_user_id: 'GSHKPN02', has_eservice_password: false }
    renderIt()
    expect(await screen.findByText(/no e-Service signing password stored/i))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Apply signature/ })).toBeDisabled()
    // A refusal with no remedy is just an obstacle.
    expect(screen.getByRole('link', { name: /CR Credentials/ }))
      .toHaveAttribute('href', '/cr-credentials')
  })

  it('still signs when the stored account id is not readable back', async () => {
    // load_eservice() falls back to the legacy presentor_account_id, which
    // get_metadata deliberately never returns. The password is what decides.
    CREDENTIALS = { eservice_user_id: null, has_eservice_password: true }
    renderIt()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply signature/ })).toBeEnabled())
  })

  it('does not hide the manual route when the credential lookup fails', async () => {
    get.mockImplementation(url => String(url).includes('/tpsi/credentials')
      ? Promise.reject(new Error('offline'))
      : Promise.resolve(RETURN_DATA))
    renderIt()
    expect(await screen.findByRole('radio', { name: /Manual/ })).toBeEnabled()
  })

  it('never offers to retry a CR rejection', async () => {
    const user = userEvent.setup()
    // 422: CR rejected the signature. 502 now means CR could not be reached.
    post.mockRejectedValue(Object.assign(new Error('tampered'), { status: 422 }))
    renderIt()
    await user.click(screen.getByRole('button', { name: /Apply signature/ }))
    // Raised to the page, which is the only place a refusal is drawn. The
    // stage used to repeat the hint in a yellow box of its own, half a page
    // under a banner that had already said it (Levi 2026-09-03).
    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        retry: false,
        hint: expect.stringMatching(/do not simply retry/i),
      })))
    expect(document.querySelector('.alert')).toBeNull()
  })

  it('uploads the wet-signed form as multipart on the manual route', async () => {
    const user = userEvent.setup()
    renderIt({ signing_method: 'manual' })
    const file = new File(['%PDF'], 'signed.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('Wet-signed NAR1'), file)
    await waitFor(() => expect(upload).toHaveBeenCalled())
    expect(upload.mock.calls[0][0]).toBe('/cases/c1/manual-sign')
    expect(upload.mock.calls[0][1].get('file')).toBe(file)
  })

  // ── v11 restorations (Q3, Block A) ──────────────────────────────────────

  it('states the balance and the fee it covers before signing', async () => {
    renderIt()
    expect(await screen.findByText(/Deposit balance/)).toBeInTheDocument()
    expect(screen.getByText(/covers the HK\$ 105.00 fee/)).toBeInTheDocument()
    expect(screen.getByText(/enquireDepositAccount/)).toBeInTheDocument()
  })

  it('says plainly when the balance will not cover the fee', async () => {
    get.mockImplementation(url => String(url).includes('/tpsi/credentials')
      ? Promise.resolve(CREDENTIALS)
      : Promise.resolve({ fee: '3480.00', balance: '90', sufficient: false }))
    renderIt()
    expect(await screen.findByText(/below the HK\$ 3,480.00 fee/)).toBeInTheDocument()
    // "Checked just now" is reassurance, and reassurance next to a blocking
    // problem reads as though the problem is handled.
    expect(screen.queryByText(/enquireDepositAccount/)).toBeNull()
  })

  it('warns about an expiring TPSI password without hiding the balance', async () => {
    const soon = new Date(Date.now() + 5 * 86400000).toISOString()
    CREDENTIALS = { ...CREDENTIALS, tpsi_password_expires_at: soon }
    renderIt()
    expect(await screen.findByText(/expires in 5 days/)).toBeInTheDocument()
    expect(screen.getByText(/Deposit balance/)).toBeInTheDocument()
  })

  it('shows no deposit pre-flight on the manual route', async () => {
    // Nothing is drawn from the deposit account there, so a balance gate is
    // one the operator can neither act on nor need.
    renderIt({ signing_method: 'manual' })
    await screen.findByText(/Choose the signed PDF/)
    expect(screen.queryByText(/Deposit balance/)).toBeNull()
  })

  it('does not preach the one-signature rule twice over', () => {
    // Removed 2026-08-31. The rule is still stated where it is actionable —
    // the "Apply the signature" card's own subtitle, beside the control it
    // constrains — rather than as a standing notice above every visit.
    renderIt()
    expect(screen.queryByText(/verifyPinSigningNar1/)).toBeNull()
    expect(screen.queryByText(/nothing is charged until Submission/)).toBeNull()
    expect(screen.getByText(/CR rejects a signature from a corporate account/))
      .toBeInTheDocument()
  })

  it('names the permission the sign button needs', () => {
    renderIt()
    expect(screen.getByText(/tpsi:write/)).toBeInTheDocument()
  })

  it('keeps the upload card, with a Replace, once a scan is attached', async () => {
    // Replacing the card with a generic success alert left an operator who had
    // attached the wrong scan with no way back.
    renderIt({ signing_method: 'manual', manual_signed_document_id: 'd1',
               manual_signed_document_version: 3 })
    expect(await screen.findByText(/Signed NAR1 attached/)).toBeInTheDocument()
    expect(screen.getByText(/Version 3/)).toBeInTheDocument()
    expect(screen.getByText(/NAR1_MANUAL_SIGN_UPLOADED/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Replace/ })).toBeEnabled()
  })

  it('offers Continue to Submission only once the return is signed', async () => {
    const onGo = vi.fn()
    const { rerender } = render(
      <MemoryRouter>
        <StageSigning caseRow={at()} canWrite onChanged={onChanged}
                      onError={onError} onGo={onGo} />
      </MemoryRouter>)
    expect(screen.queryByRole('button', { name: /Continue to Submission/ })).toBeNull()

    rerender(
      <MemoryRouter>
        <StageSigning caseRow={at({ form_status: { code: 'signed' } })} canWrite
                      onChanged={onChanged} onError={onError} onGo={onGo} />
      </MemoryRouter>)
    await userEvent.setup().click(
      screen.getByRole('button', { name: /Continue to Submission/ }))
    expect(onGo).toHaveBeenCalledWith(4)
  })

  it('does not offer the e-Sign form on the manual route', () => {
    renderIt({ signing_method: 'manual' })
    expect(screen.queryByLabelText(/e-Service signing password/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 4 · Submission — the chargeable one
// ---------------------------------------------------------------------------

describe('Submission — e-Sign', () => {
  const signed = over => at({ form_status: { code: 'signed' }, ...over })
  const renderIt = (over = {}, props = {}) => render(
    <StageSubmission caseRow={signed(over)} canSubmit
                     onChanged={onChanged} onError={onError} {...props} />)

  it('pre-flights the fee and balance before offering to file', async () => {
    renderIt()
    await waitFor(() => expect(get).toHaveBeenCalledWith('/tpsi/filings/f1/preview'))
    expect(await screen.findByText(/Fee HK\$ 105/)).toBeInTheDocument()
  })

  const withPreflight = over => {
    get.mockImplementation(url => String(url).includes('/summary')
      ? Promise.resolve(FILING_SUMMARY)
      : Promise.resolve({
          fee: '105.00', on_time_fee: '105.00', max_fee: '3480.00',
          fee_is_certain: true, balance: '12480', sufficient: true,
          fee_detail: { amount: '105.00', band: 'within 42 days of the return date',
                        return_date: '2026-08-01', days_after_deadline: -30,
                        certain: true, reason: null },
          ...over,
        }))
  }

  it('quotes the COMPUTED fee for a late return, not the on-time one', async () => {
    // Measured against live CR: a return 7 months late was billed HK$2,610
    // while the pre-flight said "Fee HK$105".
    withPreflight({
      fee: '2610.00',
      fee_detail: {
        amount: '2610.00',
        band: 'more than 6 months after but within 9 months of the return date',
        return_date: '2026-01-01', days_after_deadline: 196,
        certain: true, reason: null,
      },
    })
    renderIt()
    expect(await screen.findByText(/Fee HK\$ 2,610\.00/)).toBeInTheDocument()
    expect(screen.getByText(/within 9 months of the return date/)).toBeInTheDocument()
    expect(screen.getByText(/2026-01-01/)).toBeInTheDocument()
    // "late" sits in its own <b>, so the sentence is split across elements —
    // read the fee panel's text rather than hunting for one node. It is a
    // `.card-note`, not an `.alert`: `.alert` on the workflow now means "what
    // you just did was refused" and is drawn once, at the top of the page.
    expect(document.querySelector('.card-note').textContent)
      .toMatch(/This return is\s*late/)
  })

  it('the acknowledgement names the amount actually being spent', async () => {
    // Ticking "charges the fee" while believing it is HK$105 is not consent to
    // spend HK$2,610.
    withPreflight({ fee: '2610.00' })
    renderIt()
    expect(await screen.findByRole('button',
      { name: /deducts HK\$ 2,610\.00/ })).toBeInTheDocument()
  })

  it('does not call an on-time return late', async () => {
    withPreflight()
    renderIt()
    await screen.findByText(/Fee HK\$ 105\.00/)
    expect(document.querySelector('.card-note').textContent).not.toMatch(/is\s*late/)
    expect(screen.getByText(/within 42 days of the return date/)).toBeInTheDocument()
  })

  it('says why the fee is unknown rather than quoting a number as fact', async () => {
    withPreflight({
      fee: '3480.00', fee_is_certain: false,
      fee_detail: { amount: '3480.00', band: 'up to HK$3480.00', return_date: null,
                    days_after_deadline: null, certain: false,
                    reason: 'the incorporation date is required to work out the registration fee' },
    })
    renderIt()
    expect(await screen.findByText(/could not be worked out/)).toBeInTheDocument()
    expect(screen.getByText(/incorporation date is required/)).toBeInTheDocument()
    expect(screen.getByText(/checked against the highest it could be/)).toBeInTheDocument()
  })

  it('summarises the FROZEN return, not the live company profile', async () => {
    // The last thing read before an irreversible charge must be what CR will
    // actually receive. RETURN_DATA (the profile) and FILING_SUMMARY (the
    // snapshot) carry different director names precisely so this can tell
    // which one reached the screen.
    renderIt()
    await screen.findByText(/Final summary/)
    await waitFor(() => expect(get).toHaveBeenCalledWith('/tpsi/filings/f1/summary'))
    expect(screen.getByText('CHAN, TAI MAN')).toBeInTheDocument()
    expect(screen.queryByText('Chan Tai Man')).not.toBeInTheDocument()
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining('/return-data'))
  })

  it('BLOCKS filing when the deposit balance will not cover the fee', async () => {
    const user = userEvent.setup()
    get.mockResolvedValue({ fee: 105, balance: 12, sufficient: false })
    renderIt()
    await screen.findByText(/does not cover this filing/)
    // The acknowledgement itself is disabled, so the gate cannot be ticked past.
    expect(screen.getByRole('button', { name: /I understand this submits NAR1 to CR/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ }))
    expect(post).not.toHaveBeenCalled()
  })

  it('BLOCKS filing when the pre-flight itself failed', async () => {
    get.mockRejectedValue(Object.assign(new Error('CR down'), { status: 503 }))
    renderIt()
    await screen.findByText(/fee and balance are unavailable/)
    expect(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ })).toBeDisabled()
  })

  it('requires an explicit acknowledgement even when the balance is fine', async () => {
    renderIt()
    await screen.findByText(/Fee HK\$ 105/)
    expect(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ })).toBeDisabled()
  })

  it('files only after the charge is acknowledged, and sends confirm', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText(/Fee HK\$ 105/)
    await user.click(screen.getByRole('button', { name: /I understand this submits NAR1 to CR/ }))
    await user.click(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/tpsi/filings/f1/submit', { confirm: true }))
  })

  it('hides filing entirely from someone without tpsi:submit', () => {
    renderIt({}, { canSubmit: false })
    expect(screen.queryByRole('button', { name: /Submit NAR1 to Companies Registry/ })).not.toBeInTheDocument()
    expect(screen.getByText(/tpsi:submit/)).toBeInTheDocument()
  })

  // ── v11 restorations (Q3, Block B) ──────────────────────────────────────

  it('does the arithmetic — what the balance will be afterwards', async () => {
    get.mockImplementation(url => String(url).includes('/summary')
      ? Promise.resolve(FILING_SUMMARY)
      : Promise.resolve({ fee: '2610.00', max_fee: '3480.00', fee_is_certain: true,
                          on_time_fee: '105.00', balance: '12480', sufficient: true }))
    renderIt()
    // The balance now appears twice on purpose — once in the sentence above,
    // once in the box. Scoped, so this asserts the BOX did the arithmetic.
    await screen.findByText(/Balance after/)
    const box = document.querySelector('.deposit-box')
    expect(within(box).getByText('HK$ 12,480.00')).toBeInTheDocument()
    expect(within(box).getByText(/− HK\$ 2,610\.00/)).toBeInTheDocument()
    expect(within(box).getByText(/Balance after ≈ HK\$ 9,870\.00/)).toBeInTheDocument()
  })

  it('subtracts the CEILING when the fee is not computable', async () => {
    // Being optimistic here means telling the operator they will have money
    // left that they may not. The blanket mock is fee_is_certain: false.
    renderIt()
    expect(await screen.findByText(/− HK\$ 3,480\.00/)).toBeInTheDocument()
    expect(screen.getByText(/at most/)).toBeInTheDocument()
    expect(screen.getByText(/Balance after ≈ HK\$ 9,000\.00/)).toBeInTheDocument()
  })

  it('boxes the irreversible step and names its permission', async () => {
    renderIt()
    expect(await screen.findByText(/Irreversible action — two-step confirmation/))
      .toBeInTheDocument()
    expect(screen.getByText(/a separate permission from tpsi:write/)).toBeInTheDocument()
  })

  it('offers a way back to signing rather than only forwards', async () => {
    const onGo = vi.fn()
    renderIt({}, { onGo })
    await userEvent.setup().click(
      await screen.findByRole('button', { name: /Cancel — back to signing/ }))
    expect(onGo).toHaveBeenCalledWith(3)
  })

  it('downloads the filled Form NAR1, not a rendering of the summary', async () => {
    // Levi 2026-08-30, asked for by name. The endpoint served the facsimile
    // and nothing on this screen called it.
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Download NAR1 PDF/ }))
    await waitFor(() => expect(blob).toHaveBeenCalledWith('/tpsi/filings/f1/pdf'))
  })

  it('says so when the NAR1 PDF cannot be produced', async () => {
    blob.mockRejectedValue(Object.assign(new Error('template missing'), { status: 500 }))
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Download NAR1 PDF/ }))
    expect(await screen.findByText(/Could not produce the NAR1 PDF/)).toBeInTheDocument()
  })

  // ── spec §6: the pre-submit drift gate ──────────────────────────────────

  const DRIFT = Object.assign(
    new Error('the validated form no longer matches the company record'),
    {
      status: 409,
      reason: 'drift',
      differences: [
        { path: 'indDirList/indDir/stdAddress/stEstLotVlg',
          field: 'Director (individual) · Address · Street / estate / lot / village',
          validated: 'Raggatan 9, Stockholm 11859',
          current: 'Raggatan 14, Stockholm 11859' },
        { path: 'indDirList/indDir[2]/indvEngSname',
          field: 'Director (individual) 2 · Surname (English)',
          validated: 'WONG', current: null },
      ],
    })

  async function attemptDriftedSubmit() {
    const user = userEvent.setup()
    post.mockRejectedValue(DRIFT)
    renderIt()
    await screen.findByText(/Fee HK\$ 105/)
    await user.click(screen.getByRole('button', { name: /I understand this submits NAR1 to CR/ }))
    await user.click(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ }))
    return user
  }

  it('hands the refusal UP, with every field that moved intact', async () => {
    // The stage no longer draws this. Spec §6's refusal is rendered by
    // RefusalDetail in the page banner, as one comparison card per field —
    // see RefusalDetail.test.jsx and CaseWorkflowPage.test.jsx. Drawing it
    // here as well is what produced a detailed refusal at the top of the page
    // and a vague one beside the button (Levi 2026-09-03).
    await attemptDriftedSubmit()
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith(
      expect.objectContaining({
        reason: 'drift',
        differences: DRIFT.differences,
      })))
  })

  it('draws no refusal of its own beside the button', async () => {
    await attemptDriftedSubmit()
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(screen.queryByTestId('drift-panel')).not.toBeInTheDocument()
    // And nothing took its place: no alert at all inside the stage.
    expect(document.querySelector('.alert')).toBeNull()
  })

  it('clears the acknowledgement, because it was for a stale document', async () => {
    await attemptDriftedSubmit()
    // The operator ticked to acknowledge a charge against a return that has
    // since been shown to be out of date. Leaving it ticked would let a second
    // press file it without a fresh decision.
    await waitFor(() => expect(
      screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ }))
      .toBeDisabled())
  })

  it('leaves an ORDINARY 409 to the page banner', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error('filing is not signed'), { status: 409 }))
    renderIt()
    await screen.findByText(/Fee HK\$ 105/)
    await user.click(screen.getByRole('button', { name: /I understand this submits NAR1 to CR/ }))
    await user.click(screen.getByRole('button', { name: /Submit NAR1 to Companies Registry/ }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'filing is not signed' })))
  })
})

describe('Submission — manual', () => {
  // Spec §4: the CR receipt scan is now half the gate on Record, so the default
  // case here has one attached. Tests ABOUT the gate override it explicitly.
  const manual = over => at({
    signing_method: 'manual', manual_receipt_document_id: 'r1',
    manual_receipt_document_version: 1, ...over,
  })
  const renderIt = (over = {}, props = {}) => render(
    <StageSubmission caseRow={manual(over)} canSubmit
                     onChanged={onChanged} onError={onError} {...props} />)

  /** The other half of the gate — the two figures the audit trail reads. */
  const fillRequired = async user => {
    await user.type(screen.getByLabelText('Case number'), '141945492')
    await user.type(screen.getByLabelText('Total amount'), '105.00')
  }

  it('NEVER calls CR — recording is not filing', async () => {
    const user = userEvent.setup()
    renderIt()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: /Record the filing/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    // The one call is the case endpoint; nothing under /tpsi/ is touched.
    expect(post.mock.calls.every(c => !String(c[0]).startsWith('/tpsi/'))).toBe(true)
    expect(post.mock.calls[0][0]).toBe('/cases/c1/manual-submit')
  })

  it('sends CR\'s own receipt vocabulary, with the payment lines', async () => {
    const user = userEvent.setup()
    renderIt()
    await fillRequired(user)
    await user.type(screen.getByLabelText('Receipt no.'), 'D77000418931')
    await user.click(screen.getByRole('button', { name: /Record the filing/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const { receipt } = post.mock.calls[0][1]
    expect(receipt.caseNo).toBe('141945492')
    expect(receipt.paymentRcptList[0].rcptNo).toBe('D77000418931')
  })

  it('shows EVERY problem with the receipt at once', async () => {
    // They are copying off a paper receipt and must not discover the missing
    // fields one round trip at a time.
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(
      new Error({ message: 'receipt is incomplete', problems: ['caseNo: required', 'brNo: required'] }),
      { status: 400 }))
    renderIt()
    await fillRequired(user)
    await user.click(screen.getByRole('button', { name: /Record the filing/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(await screen.findByText(/The receipt is incomplete/)).toBeInTheDocument()
  })

  // ---- spec §4: the CR receipt document ----------------------------------

  it('will not record a filing until the CR receipt is attached', async () => {
    const user = userEvent.setup()
    renderIt({ manual_receipt_document_id: null })
    await fillRequired(user)
    expect(screen.getByRole('button', { name: /Record the filing/ })).toBeDisabled()
    // AT THE BUTTON, not in a page banner a screen and a half above it.
    expect(screen.getByTestId('manual-submit-block'))
      .toHaveTextContent(/Attach the CR receipt/)
  })

  it('will not record a filing until the receipt figures are typed', () => {
    renderIt()
    expect(screen.getByRole('button', { name: /Record the filing/ })).toBeDisabled()
    expect(screen.getByTestId('manual-submit-block'))
      .toHaveTextContent(/Complete the receipt fields/)
  })

  it('says BOTH halves are missing when both are', () => {
    renderIt({ manual_receipt_document_id: null })
    expect(screen.getByTestId('manual-submit-block'))
      .toHaveTextContent(/Attach the CR receipt and complete the receipt fields/)
  })

  it('arms Record once the receipt is attached and the figures are typed', async () => {
    const user = userEvent.setup()
    renderIt()
    await fillRequired(user)
    expect(screen.getByRole('button', { name: /Record the filing/ })).toBeEnabled()
    expect(screen.queryByTestId('manual-submit-block')).not.toBeInTheDocument()
  })

  it('uploads the receipt to the case, not to the company', async () => {
    const user = userEvent.setup()
    renderIt({ manual_receipt_document_id: null })
    const file = new File(['%PDF-1.4'], 'receipt.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('CR filing receipt'), file)
    await waitFor(() => expect(upload).toHaveBeenCalled())
    expect(upload.mock.calls[0][0]).toBe('/cases/c1/manual-receipt')
    // A receipt is evidence for one annual return. Owning it by company would
    // have next year's upload version over this year's.
    expect(upload.mock.calls[0][1].get('file')).toBe(file)
  })

  it('names the attached receipt by VERSION, because the case has no filename', () => {
    renderIt({ manual_receipt_document_version: 3 })
    expect(screen.getByText(/CR receipt attached/)).toBeInTheDocument()
    expect(screen.getByText(/Version 3/)).toBeInTheDocument()
  })

  it('can add another payment line', async () => {
    const user = userEvent.setup()
    renderIt()
    expect(screen.getAllByLabelText(/Receipt no\./)).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: /Add payment line/ }))
    expect(screen.getAllByLabelText(/Receipt no\./)).toHaveLength(2)
  })

  it('gates recording on tpsi:submit, because it closes the case as filed', () => {
    renderIt({}, { canSubmit: false })
    expect(screen.queryByRole('button', { name: /Record the filing/ })).not.toBeInTheDocument()
    expect(screen.getByText(/tpsi:submit/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 5 · Confirmation
// ---------------------------------------------------------------------------

describe('Confirmation', () => {
  const receipt = {
    caseNo: '141945492', brNo: '2100028', engCoyName: 'Harbour Tech Ltd.',
    totalAmount: '105.00',
    paymentRcptList: [{ rcptNo: 'D77000418931', revCode: 'R1', docShtFrm: 'NAR1', amtChrg: '105.00' }],
  }
  // Inside a router: the stage no longer dead-ends — it offers a way back to
  // the company and to the case list, both of which navigate.
  const renderIt = (over = {}) => renderRouted(
    <StageConfirmation caseRow={at({ receipt, ...over })} canRead onError={onError} />)

  it('opens with a hero saying the statutory job is done', () => {
    renderIt({ form_status: { code: 'registered', label: 'Registered' } })
    expect(screen.getByText('NAR1 filed & confirmed by CR')).toBeInTheDocument()
    expect(screen.getByText(/marked/)).toBeInTheDocument()
  })

  it('does not claim CR confirmed a filing CR has not confirmed', () => {
    // Delivered is not registered. Saying "confirmed by CR" before CR has said
    // so is the one claim this screen must not make.
    renderIt({ form_status: { code: 'submitted', label: 'Submitted' } })
    expect(screen.queryByText('NAR1 filed & confirmed by CR')).toBeNull()
    expect(screen.getByText(/has been delivered/)).toBeInTheDocument()
  })

  it('does not dead-end — it offers a way back to the work', () => {
    renderIt()
    expect(screen.getByRole('button', { name: /View company profile/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Back to Post-incorporation/ })).toBeInTheDocument()
  })

  it('renders the receipt CR issued', () => {
    renderIt()
    expect(screen.getByText('141945492')).toBeInTheDocument()
    expect(screen.getByText('D77000418931')).toBeInTheDocument()
  })

  it('renders a manual receipt identically — the register does not care how it got there', () => {
    renderIt({ manual_submitted_at: '2026-08-20T00:00:00Z' })
    expect(screen.getByText('141945492')).toBeInTheDocument()
    expect(screen.getByText(/Filed outside the portal/)).toBeInTheDocument()
  })

  // The CR status check was REMOVED (Levi 2026-09-02). It could not do the job
  // its own copy claimed: the result lived in useState and vanished on reload,
  // nothing ever writes the `registered` stage it was looking for, and
  // `_FINISHED` already counts `submitted`, so the case reads Completed from
  // the moment the receipt exists. It also spent a CR AUTHENTICATION per press,
  // and repeated CR auth failures lock the account.
  it('ends at the receipt and asks CR for nothing', async () => {
    renderIt()
    expect(screen.queryByRole('button', { name: /Check CR status/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/What CR holds now/)).not.toBeInTheDocument()
    // The whole screen is now a read of the case. No request leaves it.
    expect(get).not.toHaveBeenCalled()
  })

  it('says the case is Completed rather than sending the reader off to check', () => {
    renderIt()
    expect(screen.getByText(/issued the receipt below/)).toBeInTheDocument()
    expect(screen.queryByText(/Check the CR document status/)).not.toBeInTheDocument()
  })

  it('still says plainly when there is no receipt to show', () => {
    renderIt({ receipt: null })
    expect(screen.getByText(/No receipt recorded/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Permissions — every stage, every combination that changes what renders
//
// The workflow is where the levels actually separate: `nar1:write` drives the
// case, `tpsi:write` talks to CR, and `tpsi:submit` spends money. A role can
// hold any one without the others, and each stage has to withhold exactly its
// own actions — WITHOUT rendering them disabled (Levi 2026-09-04).
// ---------------------------------------------------------------------------

describe('Stage permissions — controls are absent, never merely disabled', () => {
  const noDisabledButtons = () =>
    screen.queryAllByRole('button')
      .filter(b => b.hasAttribute('disabled'))
      .map(b => b.textContent.trim())

  describe('Data Verification without nar1:write', () => {
    const renderIt = (over = {}) => render(
      <StageDataVerification caseRow={at(over)} canWrite={false} canValidate
                             onChanged={onChanged} onError={onError} />)

    it('renders the manual checks as facts, not as tick targets', async () => {
      renderIt({ aml_cleared: true, accounts_ready: false })
      await screen.findByText('Manual checks')

      // The ANSWER survives — it is why the case can or cannot advance — but
      // there is nothing to press.
      const aml = screen.getByTestId('check-AML screening cleared')
      expect(aml).toHaveTextContent('Yes')
      expect(screen.getByTestId('check-e-Reg accounts created'))
        .toHaveTextContent('No')
      expect(screen.queryByRole('button', { name: /AML screening cleared/ }))
        .not.toBeInTheDocument()
    })

    it('offers no signing-capacity picker', async () => {
      renderIt()
      await screen.findByText('Manual checks')
      expect(screen.queryByLabelText('Signing capacity')).not.toBeInTheDocument()
    })
  })

  describe('Data Verification without tpsi:write', () => {
    const renderIt = () => render(
      <StageDataVerification caseRow={at({ form_status: { code: 'draft' }, filing_id: null })}
                             canWrite canValidate={false}
                             onChanged={onChanged} onError={onError} />)

    it('renders no Validate button, and says who can', async () => {
      renderIt()
      await screen.findByText('Manual checks')

      expect(screen.queryByRole('button', { name: /Validate with CR/ }))
        .not.toBeInTheDocument()
      expect(screen.getByText(/validating with CR is not available to your role/))
        .toBeInTheDocument()
    })

    it('leaves no disabled button behind', async () => {
      renderIt()
      await screen.findByText('Manual checks')
      expect(noDisabledButtons()).toEqual([])
    })
  })

  describe('Data Verification WITH tpsi:write', () => {
    it('asks for tpsi:write, not tpsi:read', async () => {
      // Validating rebuilds the draft first (`filings/prepare`, tpsi:write) and
      // only then asks CR to check it. The tag used to promise `tpsi:read`,
      // which could never complete the action.
      render(<StageDataVerification caseRow={at({ form_status: { code: 'draft' }, filing_id: null })}
                                    canWrite canValidate
                                    onChanged={onChanged} onError={onError} />)
      await screen.findByText('Manual checks')

      expect(screen.getByRole('button', { name: /Validate with CR/ })).toBeInTheDocument()
      const tag = screen.getByText(/validation is free/)
      expect(tag).toHaveTextContent('tpsi:write')
      expect(tag).not.toHaveTextContent('tpsi:read')
    })
  })

  describe('Client Verification without nar1:write', () => {
    const renderIt = (over = {}) => renderRouted(
      <StageClientVerification caseRow={at(over)} canWrite={false}
                               onChanged={onChanged} onError={onError} onWarn={onWarn} />)

    it('renders no Send, no reviewed tick and no recipient editing', async () => {
      renderIt()
      await screen.findByText(/Client's answer/)

      expect(screen.queryByRole('button', { name: /Send to client/ }))
        .not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Client approved/ }))
        .not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Client declined/ }))
        .not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Add recipient/ }))
        .not.toBeInTheDocument()
    })

    it('still SHOWS who the return would go to', async () => {
      // The recipient list is the thing a reviewer is here to check. Only the
      // ways to change it are gone.
      renderIt()
      await screen.findByText(/Client's answer/)

      const chips = await screen.findByTestId('recipient-chips')
      expect(chips).toHaveTextContent('chan@example.com')
      expect(within(chips).queryByRole('button', { name: /Remove chan/ }))
        .not.toBeInTheDocument()
    })

    it('says who can send, rather than showing an empty stage', async () => {
      renderIt()
      await screen.findByText(/Client's answer/)
      expect(screen.getByText(/sending it to the client is not available/))
        .toBeInTheDocument()
    })
  })

  describe('Signing without nar1:write', () => {
    it('shows the chosen method as a fact, with no radio to change it', async () => {
      renderRouted(<StageSigning caseRow={at({ signing_method: 'manual' })}
                                 canWrite={false} onChanged={onChanged}
                                 onError={onError} />)
      await screen.findByText('Signing method')

      expect(screen.getByTestId('signing-method')).toHaveTextContent('Manual')
      expect(screen.queryByRole('radio')).not.toBeInTheDocument()
      expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    })

    it('renders no upload zone for the wet-signed scan', async () => {
      renderRouted(<StageSigning caseRow={at({ signing_method: 'manual' })}
                                 canWrite={false} onChanged={onChanged}
                                 onError={onError} />)
      await screen.findByText('Signing method')

      expect(screen.queryByRole('button', { name: /Choose the signed PDF/ }))
        .not.toBeInTheDocument()
      expect(screen.getByText(/No signed scan attached yet/)).toBeInTheDocument()
    })
  })

  describe('Signing without tpsi:write', () => {
    it('renders no Apply signature, and names the permission', async () => {
      renderRouted(<StageSigning caseRow={at({ signing_method: 'esign' })}
                                 canWrite={false} onChanged={onChanged}
                                 onError={onError} />)
      await screen.findByText('Signing method')

      expect(screen.queryByRole('button', { name: /Apply signature/ }))
        .not.toBeInTheDocument()
      expect(screen.getByText(/signing is not available to your role/))
        .toBeInTheDocument()
    })
  })

  describe('Submission without tpsi:submit', () => {
    it('renders no submit gate on the e-Sign path', async () => {
      render(<StageSubmission caseRow={at({ signing_method: 'esign' })}
                              canSubmit={false} onChanged={onChanged}
                              onError={onError} />)
      await waitFor(() => expect(get).toHaveBeenCalled())

      expect(screen.queryByRole('button', { name: /Submit NAR1/ }))
        .not.toBeInTheDocument()
      expect(await screen.findByText(/Filing requires the/)).toBeInTheDocument()
    })

    it('renders no receipt FORM on the manual path — the fields are controls too', async () => {
      render(<StageSubmission caseRow={at({ signing_method: 'manual' })}
                              canSubmit={false} onChanged={onChanged}
                              onError={onError} />)
      await screen.findByText(/Record the Companies Registry receipt/)

      // Nothing has been recorded yet, so every field would be an empty box
      // this role may not type in, above an upload zone that refuses the file.
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Record the filing/ }))
        .not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Choose the receipt/ }))
        .not.toBeInTheDocument()
      expect(screen.getByText(/requires the/)).toHaveTextContent('tpsi:submit')
    })

    it('leaves no disabled button behind on either path', async () => {
      for (const method of ['esign', 'manual']) {
        const { unmount } = render(
          <StageSubmission caseRow={at({ signing_method: method })}
                           canSubmit={false} onChanged={onChanged} onError={onError} />)
        await waitFor(() => expect(get).toHaveBeenCalled())
        expect(noDisabledButtons(), method).toEqual([])
        unmount()
      }
    })
  })

  describe('Submission WITH tpsi:submit', () => {
    it('gives the manual path its form back', async () => {
      render(<StageSubmission caseRow={at({ signing_method: 'manual' })}
                              canSubmit onChanged={onChanged} onError={onError} />)
      await screen.findByText(/Record the Companies Registry receipt/)

      expect(screen.queryAllByRole('textbox').length).toBeGreaterThan(0)
      expect(screen.getByRole('button', { name: /Record the filing/ }))
        .toBeInTheDocument()
    })
  })
})
