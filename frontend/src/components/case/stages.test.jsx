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

  it('reuses an existing filing rather than orphaning a second draft', async () => {
    const user = userEvent.setup()
    renderIt({ form_status: { code: 'validation_failed', failed: true, faults: ['x'] } })
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls.some(c => c[0] === '/tpsi/filings/prepare')).toBe(false)
    expect(post.mock.calls[0][0]).toBe('/tpsi/filings/f1/validate')
  })

  it('renders EVERY CR fault, not just the first', async () => {
    renderIt({
      form_status: {
        code: 'validation_failed', failed: true,
        faults: ['Partial HKID is required', 'Signatory date precedes appointment'],
      },
    })
    expect(screen.getByText('Partial HKID is required')).toBeInTheDocument()
    expect(screen.getByText('Signatory date precedes appointment')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()   // the count pill
  })

  it('says the snapshot is frozen once CR has validated it', () => {
    renderIt()
    expect(screen.getByText(/CR-signed snapshot frozen/)).toBeInTheDocument()
  })

  it('explains a shut CR window instead of just failing', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error('outside the window'), { status: 503 }))
    renderIt({ form_status: { code: 'draft' }, filing_id: null })
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    expect(await screen.findByText(/10:00–16:00 Hong Kong time/)).toBeInTheDocument()
  })

  it('restarts verification through the case, discarding the snapshot', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: /Restart verification/ }))
    await user.click(screen.getByRole('button', { name: /Restart — back to Data Verification/ }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/cases/c1', { restart_verification: true }))
  })

  it('asks before discarding a CR-signed snapshot', async () => {
    // One click used to discard the snapshot, the client's approval and any
    // signature taken since. The wireframe puts it behind a confirmation.
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: /Restart verification/ }))

    expect(screen.getByRole('alertdialog', { name: 'Restart verification' }))
      .toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 2 · Client Verification
// ---------------------------------------------------------------------------

describe('Client Verification', () => {
  const renderIt = (over = {}) => render(
    <StageClientVerification caseRow={at(over)} canWrite
                             onChanged={onChanged} onError={onError} />)

  it('renders the PDF from the CR-validated snapshot', async () => {
    renderIt()
    await waitFor(() => expect(blob).toHaveBeenCalledWith('/tpsi/filings/f1/pdf'))
  })

  // Levi 2026-08-30. The interlock itself is enforced in the backend
  // (email_service.TEST_RECIPIENTS); these cover only the operator being told.
  it('says nothing is really sent to the client, in a test environment', async () => {
    auth = { isTestEnv: true }
    renderIt()
    expect(await screen.findByText(/will not actually be sent to the client/i))
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
    expect(screen.queryByText(/will not actually be sent to the client/i))
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

  it('says so when the deployment delivered nothing', async () => {
    // Otherwise an operator believes two directors were emailed when mail is
    // stubbed out and nobody received anything.
    const user = userEvent.setup()
    post.mockResolvedValue({ transport: 'console' })
    renderIt()
    await reviewAndSend(user)
    expect(await screen.findByText(/Nothing was actually delivered/))
      .toBeInTheDocument()
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

  it('defaults to e-Sign — nothing switches to manual by itself', () => {
    renderIt({ signing_method: null })
    expect(screen.getByRole('tab', { name: /e-Sign via CR/ }))
      .toHaveAttribute('aria-selected', 'true')
  })

  it('warns that choosing manual takes the filing off the portal', async () => {
    renderIt({ signing_method: 'manual' })
    expect(screen.getByText(/This filing leaves G-FlowDesk/)).toBeInTheDocument()
    expect(screen.getByText(/refuse to e-file this case afterwards/)).toBeInTheDocument()
  })

  it('records the chosen method on the case', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('tab', { name: /Manual/ }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/cases/c1', { signing_method: 'manual' }))
  })

  it('signs as the logged-in user, sending nothing about who signs', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(await screen.findByRole('button', { name: /Sign the return/ }))
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
    expect(screen.getByRole('button', { name: /Sign the return/ })).toBeDisabled()
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
      expect(screen.getByRole('button', { name: /Sign the return/ })).toBeEnabled())
  })

  it('does not hide the manual route when the credential lookup fails', async () => {
    get.mockImplementation(url => String(url).includes('/tpsi/credentials')
      ? Promise.reject(new Error('offline'))
      : Promise.resolve(RETURN_DATA))
    renderIt()
    expect(await screen.findByRole('tab', { name: /Manual/ })).toBeEnabled()
  })

  it('never offers to retry a CR rejection', async () => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(new Error('tampered'), { status: 502 }))
    renderIt()
    await user.click(screen.getByRole('button', { name: /Sign the return/ }))
    expect(await screen.findByText(/do not simply retry/i)).toBeInTheDocument()
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
    expect(await screen.findByText(/Fee HK\$105/)).toBeInTheDocument()
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
    expect(await screen.findByText(/Fee HK\$2610.00/)).toBeInTheDocument()
    expect(screen.getByText(/within 9 months of the return date/)).toBeInTheDocument()
    expect(screen.getByText(/2026-01-01/)).toBeInTheDocument()
    // "late" sits in its own <b>, so the sentence is split across elements —
    // read the alert's text rather than hunting for one node.
    expect(document.querySelector('.alert').textContent)
      .toMatch(/This return is\s*late/)
  })

  it('the acknowledgement names the amount actually being spent', async () => {
    // Ticking "charges the fee" while believing it is HK$105 is not consent to
    // spend HK$2,610.
    withPreflight({ fee: '2610.00' })
    renderIt()
    expect(await screen.findByRole('button',
      { name: /charges HK\$2610\.00/ })).toBeInTheDocument()
  })

  it('does not call an on-time return late', async () => {
    withPreflight()
    renderIt()
    await screen.findByText(/Fee HK\$105.00/)
    expect(document.querySelector('.alert').textContent).not.toMatch(/is\s*late/)
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
    expect(screen.getByRole('button', { name: /I understand this files the return/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /File the return/ })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /File the return/ }))
    expect(post).not.toHaveBeenCalled()
  })

  it('BLOCKS filing when the pre-flight itself failed', async () => {
    get.mockRejectedValue(Object.assign(new Error('CR down'), { status: 503 }))
    renderIt()
    await screen.findByText(/Could not reach CR for the fee and balance/)
    expect(screen.getByRole('button', { name: /File the return/ })).toBeDisabled()
  })

  it('requires an explicit acknowledgement even when the balance is fine', async () => {
    renderIt()
    await screen.findByText(/Fee HK\$105/)
    expect(screen.getByRole('button', { name: /File the return/ })).toBeDisabled()
  })

  it('files only after the charge is acknowledged, and sends confirm', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByText(/Fee HK\$105/)
    await user.click(screen.getByRole('button', { name: /I understand this files the return/ }))
    await user.click(screen.getByRole('button', { name: /File the return/ }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/tpsi/filings/f1/submit', { confirm: true }))
  })

  it('hides filing entirely from someone without tpsi:submit', () => {
    renderIt({}, { canSubmit: false })
    expect(screen.queryByRole('button', { name: /File the return/ })).not.toBeInTheDocument()
    expect(screen.getByText(/tpsi:submit/)).toBeInTheDocument()
  })
})

describe('Submission — manual', () => {
  const manual = over => at({ signing_method: 'manual', ...over })
  const renderIt = (over = {}, props = {}) => render(
    <StageSubmission caseRow={manual(over)} canSubmit
                     onChanged={onChanged} onError={onError} {...props} />)

  it('NEVER calls CR — recording is not filing', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.click(screen.getByRole('button', { name: /Record the filing/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    // The one call is the case endpoint; nothing under /tpsi/ is touched.
    expect(post.mock.calls.every(c => !String(c[0]).startsWith('/tpsi/'))).toBe(true)
    expect(post.mock.calls[0][0]).toBe('/cases/c1/manual-submit')
  })

  it('sends CR\'s own receipt vocabulary, with the payment lines', async () => {
    const user = userEvent.setup()
    renderIt()
    await user.type(screen.getByLabelText('Case number'), '141945492')
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
    await user.click(screen.getByRole('button', { name: /Record the filing/ }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(await screen.findByText(/The receipt is incomplete/)).toBeInTheDocument()
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
  const renderIt = (over = {}) => render(
    <StageConfirmation caseRow={at({ receipt, ...over })} canRead onError={onError} />)

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

  it('asks CR what it now holds, by the receipt case number', async () => {
    const user = userEvent.setup()
    get.mockResolvedValue([{ documentName: 'NAR1', documentStatus: 'Registered',
                             submissionDate: '21/08/2026' }])
    renderIt()
    await user.click(screen.getByRole('button', { name: /Check CR status/ }))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/tpsi/doc-status?case_no=141945492'))
    expect(await screen.findByText('Registered')).toBeInTheDocument()
  })

  it('does not offer a CR status check with no case number to ask about', () => {
    renderIt({ receipt: null })
    expect(screen.queryByRole('button', { name: /Check CR status/ })).not.toBeInTheDocument()
    expect(screen.getByText(/No receipt recorded/)).toBeInTheDocument()
  })
})
