import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CaseWorkflowPage from './CaseWorkflowPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ caseId: 'c1' }) }
})

const scrollToTop = vi.fn()
vi.mock('../lib/scroll.js', () => ({ scrollToTop: (...a) => scrollToTop(...a) }))

vi.mock('../components/AuditTrailTab.jsx', () => ({
  default: ({ caseId }) => <div data-testid="audit-trail">{caseId}</div>,
}))

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn()
const blob = vi.fn(); const upload = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    blob: (...a) => blob(...a), upload: (...a) => upload(...a), put: vi.fn(),
  },
}))

// A case that has cleared every gate except filing — opens on Submission.
const CASE = {
  id: 'c1', case_no: 'NAR-2026-0041', entity_id: 'e7',
  company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
  // The composite object the backend sends (nar1_case_status.derive), NOT a
  // bare code — rendering the object is React error #31, which blanks the page.
  case_status: 'live',
  workflow_status: { code: 'submission', label: 'Submission',
                     off_portal: false, overdue: false },
  form_status: { code: 'signed', label: 'Signed', failed: false, faults: [] },
  filing_id: 'f1', days_to_anniversary: -12, signing_method: 'esign',
  verification_sent_at: '2026-08-01T09:00:00Z', client_response_at: '2026-08-03',
  client_approved: true, created_at: '2026-01-01', updated_at: '2026-08-03T10:00:00Z',
}

function caseAt(over) { return { ...CASE, ...over } }

//: What GET /cases/{id}/return-data answers — the Data Verification card reads
//: it on every render of stage 1. Declared BEFORE the generic '/cases/' branch
//: below, which would otherwise hand the card a case row and quietly render an
//: empty return.
const RETURN_DATA = {
  year: 2026, company_name: 'Harbour Tech Ltd.', br_number: '2100028',
  registered_office: 'Unit 12A, Central, Hong Kong',
  directors: ['Chan Tai Man'], secretaries: ['Get Started HK Limited'],
  signatory: { name: 'Chan Tai Man', capacity: 'Director', person_id: 'T2607D' },
  member_count: 2,
  share_classes: [{ name: 'Ordinary', total_issued: 100, currency: 'HKD' }],
  problems: [],
}

function routeGet(caseRow = CASE, extra = {}) {
  get.mockImplementation(path => {
    if (path.includes('/return-data')) {
      return Promise.resolve(extra.returnData ?? RETURN_DATA)
    }
    if (path.startsWith('/cases/')) return Promise.resolve(caseRow)
    if (path.includes('/preview')) {
      return Promise.resolve(extra.preview ?? { fee: 105, balance: 12480, sufficient: true })
    }
    if (path.includes('/doc-status')) return Promise.resolve(extra.docStatus ?? [])
    return Promise.resolve({})
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { hasPermission: () => true, isSuperAdmin: true }
  routeGet()
  blob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
  post.mockResolvedValue({}); patch.mockResolvedValue({}); upload.mockResolvedValue({})
  // jsdom has no object-URL implementation.
  global.URL.createObjectURL = vi.fn(() => 'blob:preview')
  global.URL.revokeObjectURL = vi.fn()
})

const renderPage = async () => {
  render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
  await screen.findByText(/NAR-2026-0041/)
}

describe('CaseWorkflowPage — shell', () => {
  it('reads the composite case endpoint for the id in the route', async () => {
    await renderPage()
    expect(get.mock.calls[0][0]).toBe('/cases/c1')
  })

  it('shows both statuses separately, never merged', async () => {
    await renderPage()
    // Scoped to the strip: "Submission" is also a stepper label and a page
    // title, and the point here is that the two badges are two distinct facts
    // standing side by side.
    const strip = document.querySelector('.live-strip')
    expect(within(strip).getByText('Workflow')).toBeInTheDocument()
    expect(within(strip).getByText('Submission')).toBeInTheDocument()
    expect(within(strip).getByText('CR form')).toBeInTheDocument()
    expect(within(strip).getByText('Signed')).toBeInTheDocument()
  })

  it('says CR has not seen the form yet rather than showing a blank badge', async () => {
    routeGet(caseAt({ form_status: null, filing_id: null,
                      workflow_status: { code: 'data_verification',
                                         label: 'Data Verification',
                                         off_portal: false, overdue: false } }))
    await renderPage()
    const strip = document.querySelector('.live-strip')
    expect(within(strip).getByText('Not sent to CR yet')).toBeInTheDocument()
  })

  it('titles the page with the STAGE and names the company in the breadcrumb', async () => {
    // Regression (Levi 2026-08-27): the header showed the case number and a
    // six-row property list whose company name, BRN and anniversary were all
    // blank, because GET /cases/{id} read nar1_cases directly and those three
    // facts live on the company.
    await renderPage()
    expect(screen.getByText('Submission', { selector: '.pg-title' })).toBeInTheDocument()
    const crumb = document.querySelector('.crumb')
    expect(within(crumb).getByText('Harbour Tech Ltd.')).toBeInTheDocument()
    expect(screen.getByText(/Case NAR-2026-0041/)).toBeInTheDocument()
    expect(screen.getByText(/BRN 2100028/)).toBeInTheDocument()
  })

  it('opens on the furthest stage the case has actually reached', async () => {
    await renderPage()
    const submission = screen.getByRole('tab', { name: /Submission/ })
    expect(submission).toHaveAttribute('aria-selected', 'true')
  })

  it('does NOT repeat the audit trail on the workflow screen', async () => {
    // Levi 2026-08-26: every action here is already in the Audit Log module,
    // and two places to check what happened is one too many.
    await renderPage()
    expect(screen.queryByTestId('audit-trail')).not.toBeInTheDocument()
    expect(screen.queryByText('Audit trail')).not.toBeInTheDocument()
  })

  it('offers a way back to the case list and to the company', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: 'Back to cases' }))
    expect(navigate).toHaveBeenCalledWith('/dashboard')
    await user.click(screen.getByRole('button', { name: 'Company profile' }))
    expect(navigate).toHaveBeenCalledWith('/companies/e7')
  })

  it('renders an error state when the case will not load', async () => {
    get.mockRejectedValue(new Error('nope'))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    expect(await screen.findByText(/Failed to load this case: nope/)).toBeInTheDocument()
  })
})

describe('CaseWorkflowPage — the stage gate is enforced, not just drawn', () => {
  it('locks stages the case has not reached', async () => {
    routeGet(caseAt({ form_status: null, filing_id: null, verification_sent_at: null,
                      client_approved: null, signing_method: null }))
    await renderPage()
    expect(screen.getByRole('tab', { name: /Signing/ })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('tab', { name: /Confirmation/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('refuses to open a locked stage and says what would unlock it', async () => {
    const user = userEvent.setup()
    routeGet(caseAt({ form_status: null, filing_id: null, verification_sent_at: null,
                      client_approved: null, signing_method: null }))
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Submission/ }))
    // Still on stage 1, and told why.
    expect(screen.getByRole('tab', { name: /Data Verification/ }))
      .toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText(/Complete "Data Verification" to unlock/))
      .toBeInTheDocument()
  })

  it('lets the operator move back to a stage already passed', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Data Verification/ }))
    expect(screen.getByRole('tab', { name: /Data Verification/ }))
      .toHaveAttribute('aria-selected', 'true')
  })

  it('clears the locked-stage note once the operator moves somewhere', async () => {
    // Left up, it would explain a refusal that has already been moved past.
    const user = userEvent.setup()
    routeGet(caseAt({ form_status: { code: 'validated' }, verification_sent_at: null,
                      client_approved: null }))
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Signing/ }))
    expect(await screen.findByText(/to unlock/)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Data Verification/ }))
    expect(screen.queryByText(/to unlock/)).not.toBeInTheDocument()
  })
})

describe('CaseWorkflowPage — permissions gate the consequential controls', () => {
  it('hides filing from someone without tpsi:submit', async () => {
    auth = {
      isSuperAdmin: false,
      hasPermission: (m, p) => !(m === 'tpsi' && p === 'submit'),
    }
    await renderPage()
    expect(await screen.findByText(/Filing requires the/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Submit NAR1 to Companies Registry/ })).not.toBeInTheDocument()
  })

  it('offers filing to someone who holds tpsi:submit', async () => {
    await renderPage()
    expect(await screen.findByRole('button', { name: /Submit NAR1 to Companies Registry/ })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// CR refusals on the page itself. The banner is where an operator meets them.
// ---------------------------------------------------------------------------

describe('CaseWorkflowPage — CR refusals', () => {
  const refuse = (kind, problems) => {
    post.mockRejectedValue(Object.assign(
      new Error('The Companies Registry rejected this return.'),
      // 422 since 2026-08-31: CR refusing is not a gateway failure, and a
      // 5xx body was being replaced by the edge before it reached the browser.
      { status: 422, kind, problems },
    ))
  }

  const validateFrom = async () => {
    const user = userEvent.setup()
    routeGet(caseAt({
      form_status: { code: 'draft', failed: false, faults: [] },
      filing_id: 'f1', signing_method: null,
      workflow_status: { code: 'data_verification', label: 'Data Verification' },
      aml_cleared: true, accounts_ready: true,
    }))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
  }

  it('renders CR faults as sentences, never as raw JSON', async () => {
    // CR sends [code, message] PAIRS. JSON.stringify put
    // ["ERR_MSG_INVALID_DISTRICT","Please input valid District."] on screen.
    refuse('validation', [
      ['ERR_MSG_INVALID_DISTRICT', 'Please input valid District.'],
      ['ERR_MSG_MANDATORY', 'Please check selectPersonId field.'],
    ])
    await validateFrom()

    expect(await screen.findByText('Please input valid District.')).toBeInTheDocument()
    expect(screen.getByText('Please check selectPersonId field.')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('["ERR_MSG')
    expect(document.body.textContent).not.toContain('[object Object]')
  })

  it('shouts when CR says the account is locked', async () => {
    refuse('account_locked', [['ERR_MSG_USER_ACC_LOCKED', 'User account is locked.']])
    await validateFrom()

    expect(await screen.findByText(/Account locked\./)).toBeInTheDocument()
    expect(screen.getByText(/Do not try again/i)).toBeInTheDocument()
  })

  it('does not tell someone to edit the form when the signature was refused', async () => {
    refuse('signature', [['ERR_MSG_NO_ASSOCIATION', 'Signatory not associated.']])
    await validateFrom()

    expect(await screen.findByText(/Editing the return will not fix this/i))
      .toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Restart verification — moved from stage 1 to the page header (Q3 / v11)
// ---------------------------------------------------------------------------

describe('CaseWorkflowPage — restart verification', () => {
  it('offers Restart from the header, not only from Data Verification', async () => {
    // The case fixture opens on SUBMISSION. That is the point: this is where an
    // operator discovers the snapshot is wrong, and the button used to live two
    // stages behind them.
    await renderPage()
    expect(screen.getByRole('button', { name: /Restart verification/ }))
      .toBeInTheDocument()
  })

  it('asks before discarding a CR-signed snapshot', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: /Restart verification/ }))

    expect(screen.getByRole('alertdialog', { name: 'Restart verification' }))
      .toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('discards the snapshot and returns the operator to stage 1', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: /Restart verification/ }))
    await user.click(screen.getByRole('button', { name: /Restart — back to Data Verification/ }))

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith('/cases/c1', { restart_verification: true }))
    // onChanged only ever moves FORWARD, so without an explicit step reset the
    // operator is left on Submission looking at a case with nothing to submit.
    await waitFor(() =>
      expect(screen.getByText('Data Verification', { selector: '.pg-title' }))
        .toBeInTheDocument())
  })

  it('hides Restart before there is a snapshot to discard', async () => {
    routeGet(caseAt({ form_status: { code: 'draft', label: 'Draft', failed: false },
                      filing_id: null,
                      workflow_status: { code: 'data_verification',
                                         label: 'Data Verification',
                                         off_portal: false, overdue: false } }))
    await renderPage()
    expect(screen.queryByRole('button', { name: /Restart verification/ })).toBeNull()
  })

  it('hides Restart from someone without nar1:write', async () => {
    auth = { hasPermission: (m, p) => !(m === 'nar1' && p === 'write'),
             isSuperAdmin: false }
    await renderPage()
    expect(screen.queryByRole('button', { name: /Restart verification/ })).toBeNull()
  })

  it('names the modules the screen belongs to, and they are REAL ones', async () => {
    // It used to say `case_management`, which is not a module: nothing of that
    // name exists in `role_permissions` and no administrator could grant it.
    // The one tag whose job is to answer "what do I ask for" was naming
    // something unaskable.
    await renderPage()
    expect(screen.getByText(/Modules:/)).toBeInTheDocument()
    expect(screen.getByText('nar1')).toBeInTheDocument()
    expect(screen.getByText('tpsi')).toBeInTheDocument()
    expect(screen.queryByText(/case_management/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The failure banner has to be SEEN (Levi 2026-08-31)
//
// The banner sits above the stage content, and the buttons that trigger a
// failure sit a screen or more below it. "I pressed Validate and nothing
// happened" was a correct, fully-rendered error that never entered the
// viewport — the same class of bug as the verification 409 before it.
// ---------------------------------------------------------------------------

describe('CaseWorkflowPage — a failure must reach the viewport', () => {
  const dataVerificationCase = () => ({
    ...CASE,
    form_status: { code: 'draft', failed: false, faults: [] },
    filing_id: 'f1', signing_method: null,
    workflow_status: { code: 'data_verification', label: 'Data Verification' },
    aml_cleared: true, accounts_ready: true,
  })

  it('scrolls the page to the top when CR refuses', async () => {
    // To the TOP, not to the banner (Levi 2026-08-31). scrollIntoView with
    // block:'center' centred the banner and left the crumb, the title and both
    // status badges above the fold — and it scrolled whatever the browser chose
    // as the scrolling box rather than the one AppShell actually scrolls.
    const user = userEvent.setup()
    routeGet(dataVerificationCase())
    post.mockRejectedValue(Object.assign(
      new Error('The Companies Registry rejected this return.'),
      { status: 422, kind: 'validation', problems: [['ERROR', 'Br No does not exist.']] },
    ))

    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))

    const banner = await screen.findByRole('alert')
    await waitFor(() => expect(scrollToTop).toHaveBeenCalled())
    // The element handed over must be the banner itself — the scroller is
    // found by walking UP from it, so passing anything else scrolls the wrong
    // container or nothing at all.
    expect(scrollToTop).toHaveBeenLastCalledWith(banner)
  })

  it('still shows the error when the browser cannot scroll', async () => {
    // The regression this guard exists for: the scroll threw during the commit
    // that renders the banner, so the failure vanished instead of being
    // revealed. Scrolling is a courtesy; showing the error is not.
    scrollToTop.mockImplementationOnce(() => { throw new Error('no scrolling here') })
    const user = userEvent.setup()
    routeGet(dataVerificationCase())
    post.mockRejectedValue(Object.assign(
      new Error('The Companies Registry rejected this return.'),
      { status: 422, kind: 'validation', problems: [['ERROR', 'Br No does not exist.']] },
    ))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    await user.click(screen.getByRole('button', { name: /Validate with CR/ }))
    expect(await screen.findByText(/Br No does not exist\./)).toBeInTheDocument()
  })

  it('does not scroll when nothing has failed', async () => {
    routeGet(dataVerificationCase())
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    expect(scrollToTop).not.toHaveBeenCalled()
  })

  it('does not yank the page to the top for a refusal it merely read back', async () => {
    // The banner also renders a rejection recorded EARLIER, so a reload still
    // says why. But that one is already on screen when the page opens, and
    // re-scrolling on every case reload would throw the operator to the top
    // each time they ticked a checkbox with an old rejection on record.
    routeGet({
      ...dataVerificationCase(),
      form_status: {
        code: 'validation_failed', failed: true,
        faults: [['ERROR', 'Br No does not exist.']],
      },
    })
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    expect(await screen.findByText(/Br No does not exist\./)).toBeInTheDocument()
    expect(scrollToTop).not.toHaveBeenCalled()
  })

  it('shows a recorded refusal ONCE, in the banner', async () => {
    // Levi 2026-08-31: the same faults used to appear in the page banner AND
    // in the stage card a screen below, which reads as two problems.
    routeGet({
      ...dataVerificationCase(),
      form_status: {
        code: 'validation_failed', failed: true,
        faults: [['efiling.eform.signatory.error',
                  'The signatory T260727100116S is not authorized to sign.']],
      },
    })
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    expect(screen.getAllByText(/is not authorized to sign/)).toHaveLength(1)
    expect(screen.getByText(/rejected this return/i)).toBeInTheDocument()
    expect(screen.getByText(/Nothing was charged/)).toBeInTheDocument()
  })
})

describe('CaseWorkflowPage — Restart stops at the register', () => {
  const filedCase = (over = {}) => ({
    ...CASE,
    form_status: { code: 'submitted', failed: false, faults: [], terminal: true },
    filing_id: 'f1', verification_sent_at: '2026-08-31T11:52:00Z',
    client_approved: true, signing_method: 'esign',
    workflow_status: { code: 'completed', label: 'Completed' },
    ...over,
  })

  it('offers no Restart on a return CR already holds', async () => {
    // The dialog behind that button promises to discard the CR-signed snapshot
    // and clear the client's approval — the two things the filing in the
    // register was built on. The backend refuses it with a 409; the screen
    // should not have asked in the first place.
    routeGet(filedCase())
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findAllByText(/NAR-2026-0041/)
    expect(screen.queryByRole('button', { name: /Restart verification/ })).toBeNull()
  })

  it('offers no Restart on a case filed off-portal either', async () => {
    routeGet(filedCase({
      form_status: { code: 'validated', failed: false, faults: [] },
      manual_submitted_at: '2026-08-30T09:00:00Z', signing_method: 'manual',
    }))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findAllByText(/NAR-2026-0041/)
    expect(screen.queryByRole('button', { name: /Restart verification/ })).toBeNull()
  })

  it('still offers Restart on a snapshot CR has only validated', async () => {
    // That is the case Restart exists for: the particulars are wrong and the
    // frozen snapshot has to go before anyone is asked to approve it.
    routeGet(filedCase({
      form_status: { code: 'validated', failed: false, faults: [] },
    }))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findAllByText(/NAR-2026-0041/)
    expect(screen.getByRole('button', { name: /Restart verification/ }))
      .toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// THE PRE-SUBMIT GATE, ON SCREEN (Levi 2026-09-03).
//
// The report: "I purposefully changed something in a body corporate profile
// while this form is on-going ... when I try to submit I get this error which
// is good. However it is not very user friendly." The screen showed a single
// run-on sentence at the top —
//
//   "the return could not be checked against the company record before filing,
//    so it was not submitted: the company record can no longer be mapped to a
//    NAR1: corporate party CGAHCHBAABBG DIRECTOR COMPANY LIMITED: no CR region
//    code is known for country 'HK-CH' — CR's Country & Region sheet ..."
//
// — and, half a page below it, a second yellow box reading "The case is not in
// a state that allows this."
// ---------------------------------------------------------------------------

describe('CaseWorkflowPage — the submit gate refuses', () => {
  const submitAndRefuse = async detail => {
    const user = userEvent.setup()
    post.mockRejectedValue(Object.assign(
      new Error('the backend sentence'), { status: 409, ...detail }))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText(/NAR-2026-0041/)
    await screen.findByText(/Fee HK\$/)
    await user.click(screen.getByRole('button',
      { name: /I understand this submits NAR1 to CR/ }))
    await user.click(screen.getByRole('button',
      { name: /Submit NAR1 to Companies Registry/ }))
    return user
  }

  const UNFILABLE = {
    reason: 'record_unusable',
    problems: ["corporate party CGAHCHBAABBG DIRECTOR COMPANY LIMITED: no CR "
               + "region code is known for country 'HK-CH' — CR's Country & "
               + "Region sheet (worksheet v1.0.14) carries no code, alpha-2 or "
               + "English name matching it; correct the address rather than "
               + "guessing a code CR would take the fee for and then reject"],
  }

  const DRIFTED = {
    reason: 'drift',
    differences: [
      { path: 'corpDirList/corpDir/stdAddress/ctryRegion',
        field: 'Director (body corporate) · Address · Country / region',
        validated: 'HKG', current: 'HK-CH' },
      { path: 'corpDirList/corpDir/corpEngName',
        field: 'Director (body corporate) · Name (English)',
        validated: 'CGAHCHBAABBG DIRECTOR COMPANY LIMITED', current: null },
    ],
  }

  it('names the party and the fault as separate things, not one sentence', async () => {
    await submitAndRefuse(UNFILABLE)
    const card = await screen.findByTestId('problem-card')
    expect(within(card).getByText('Corporate party')).toBeInTheDocument()
    expect(within(card).getByText('CGAHCHBAABBG DIRECTOR COMPANY LIMITED'))
      .toBeInTheDocument()
    expect(within(card).getByText(/^No CR region code is known/)).toBeInTheDocument()
  })

  it('shows the two values side by side when particulars have moved', async () => {
    await submitAndRefuse(DRIFTED)
    const cards = await screen.findAllByTestId('mismatch-card')
    expect(cards).toHaveLength(2)
    expect(within(cards[0]).getByText('HKG')).toBeInTheDocument()
    expect(within(cards[0]).getByText('HK-CH')).toBeInTheDocument()
    expect(within(cards[0]).getByText(/On the NAR1 the client approved/))
      .toBeInTheDocument()
    expect(within(cards[0]).getByText(/In the company profile now/))
      .toBeInTheDocument()
  })

  it('says the money did not move, before the detail', async () => {
    await submitAndRefuse(UNFILABLE)
    expect(await screen.findByText(/Nothing was sent to the Companies Registry/))
      .toBeInTheDocument()
  })

  it('draws the refusal EXACTLY ONCE on the page', async () => {
    // The whole complaint. A detailed banner at the top and a vague yellow
    // "The case is not in a state that allows this" beside the button is two
    // boxes for one refusal, and the redundant one says less.
    await submitAndRefuse(UNFILABLE)
    await screen.findByTestId('problem-card')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByText(/not in a state that allows this/i)).toBeNull()
  })

  it('scrolls to the top so the refusal is not left below the fold', async () => {
    await submitAndRefuse(UNFILABLE)
    const banner = await screen.findByRole('alert')
    await waitFor(() => expect(scrollToTop).toHaveBeenLastCalledWith(banner))
  })

  it('offers Restart verification where restarting is the remedy', async () => {
    await submitAndRefuse(DRIFTED)
    const banner = await screen.findByRole('alert')
    expect(within(banner).getByRole('button', { name: /Restart verification/ }))
      .toBeInTheDocument()
    // And it says WHY, next to the button: the operator has to decide which of
    // the two records is right before restarting is the correct move.
    expect(banner.querySelector('.rf-remedy-txt').textContent)
      .toMatch(/which record is right/i)
  })

  it('does NOT offer Restart when the check itself could not run', async () => {
    // Restarting discards a CR-signed snapshot. It cannot reach a database
    // that would not load.
    await submitAndRefuse({ reason: 'check_failed' })
    const banner = await screen.findByRole('alert')
    expect(within(banner).queryByRole('button', { name: /Restart verification/ }))
      .toBeNull()
    expect(within(banner).getByText(/will not help/i)).toBeInTheDocument()
  })

  it('opens the same confirmation the header Restart opens', async () => {
    // One control, not a second path that skips the warning about discarding a
    // CR-signed snapshot and a client approval.
    const user = await submitAndRefuse(DRIFTED)
    const banner = await screen.findByRole('alert')
    await user.click(within(banner).getByRole('button', { name: /Restart verification/ }))
    expect(await screen.findByRole('alertdialog', { name: /Restart verification/ }))
      .toBeInTheDocument()
  })

  it('un-ticks the acknowledgement, so a second press is a fresh decision', async () => {
    await submitAndRefuse(DRIFTED)
    await screen.findAllByTestId('mismatch-card')
    expect(screen.getByRole('button',
      { name: /Submit NAR1 to Companies Registry/ })).toBeDisabled()
  })
})


// --------------------------------------------------------------------------- #
//  Closing a case (Levi 2026-09-05) — permanent, and there is no reopen
// --------------------------------------------------------------------------- #

const CLOSED = caseAt({
  workflow_status: { code: 'closed', label: 'Closed',
                     off_portal: false, overdue: false },
  form_status: { code: 'validated', label: 'Validated by CR',
                 failed: false, faults: [] },
  verification_sent_at: null, client_approved: null,
  closed_at: '2026-09-05T02:00:00Z',
  closed_by_name: 'Levi Z.',
  closed_reason: 'client is dissolving the company',
})

describe('CaseWorkflowPage — closing a case', () => {
  it('offers Close on a live case, to someone who may write', async () => {
    await renderPage()
    expect(screen.getByRole('button', { name: 'Close case' })).toBeInTheDocument()
  })

  it('does not offer Close to a read-only role', async () => {
    auth = { hasPermission: m => m !== 'nar1', isSuperAdmin: false }
    await renderPage()
    expect(screen.queryByRole('button', { name: 'Close case' })).toBeNull()
  })

  it('withholds Close once CR holds the return', async () => {
    // The backend refuses it with a 409 — closing a filed case would record a
    // lodged statutory return as one the client abandoned. A button whose one
    // outcome is a refusal is a broken control, not a feature.
    routeGet(caseAt({
      form_status: { code: 'submitted', label: 'Filed with CR',
                     failed: false, faults: [] },
    }))
    // Not `renderPage()`: a filed case opens on Confirmation, which prints the
    // case number a second time, and its `findByText` then finds two.
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    await screen.findByText('Confirmation', { selector: '.pg-title' })
    expect(screen.queryByRole('button', { name: 'Close case' })).toBeNull()
  })

  it('will not close until a reason AND the case number are given', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: 'Close case' }))

    const confirm = screen.getByRole('button', { name: /Close case permanently/ })
    expect(confirm).toBeDisabled()

    // A reason alone is not enough.
    await user.type(screen.getByLabelText(/Why is this case not proceeding/),
                    'client is dissolving the company')
    expect(confirm).toBeDisabled()

    // Nor is the wrong case number — this is the check against closing the
    // case above the one you meant.
    await user.type(screen.getByLabelText(/to confirm/), 'NAR-2026-0040')
    expect(confirm).toBeDisabled()

    await user.clear(screen.getByLabelText(/to confirm/))
    await user.type(screen.getByLabelText(/to confirm/), 'NAR-2026-0041')
    expect(confirm).toBeEnabled()

    expect(post).not.toHaveBeenCalled()
  })

  it('posts the trimmed reason and re-reads the case rather than assuming', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: 'Close case' }))
    await user.type(screen.getByLabelText(/Why is this case not proceeding/),
                    '  client is dissolving the company  ')
    await user.type(screen.getByLabelText(/to confirm/), 'NAR-2026-0041')

    routeGet(CLOSED)
    await user.click(screen.getByRole('button', { name: /Close case permanently/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/cases/c1/close', { reason: 'client is dissolving the company' }))
    // The screen never claims the close happened; it asks the server again.
    await screen.findByText(/cannot be reopened/)
  })

  it('shows a refusal inside the dialog, where the operator still is', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: 'Close case' }))
    await user.type(screen.getByLabelText(/Why is this case not proceeding/), 'stop')
    await user.type(screen.getByLabelText(/to confirm/), 'NAR-2026-0041')

    post.mockRejectedValueOnce(Object.assign(
      new Error('the Companies Registry already holds this return'),
      { status: 409, reason: 'case_filed' }))
    await user.click(screen.getByRole('button', { name: /Close case permanently/ }))

    // In the dialog, not behind it: a banner on the page under the overlay is
    // experienced as "I pressed it and nothing happened".
    const dialog = screen.getByRole('alertdialog', { name: 'Close case' })
    await within(dialog).findByText(/already holds this return/)
    // And it can be tried again — the dialog is not left in its busy state.
    expect(screen.getByRole('button', { name: /Close case permanently/ })).toBeEnabled()
  })
})

describe('CaseWorkflowPage — a case that is already closed', () => {
  beforeEach(() => routeGet(CLOSED))

  it('says so, names who closed it and quotes their reason', async () => {
    await renderPage()
    expect(screen.getByText(/cannot be reopened/)).toBeInTheDocument()
    expect(screen.getByText(/Levi Z\./)).toBeInTheDocument()
    expect(screen.getByText('client is dissolving the company')).toBeInTheDocument()
  })

  it('titles itself "Closed" rather than rendering a blank heading', async () => {
    // `reachedStage` answers 0 for a closed case, `step` follows it, and
    // `STAGE_LABELS[-1]` is undefined — which rendered the page title AND the
    // last breadcrumb crumb as nothing at all.
    await renderPage()
    expect(screen.getByText('Closed', { selector: '.pg-title' })).toBeInTheDocument()
    const crumb = document.querySelector('.crumb')
    expect(within(crumb).getByText('Closed')).toBeInTheDocument()
    expect(document.querySelector('.pg-title').textContent).not.toBe('')
  })

  it('replaces the stepper and every stage panel', async () => {
    // Not greyed-out controls: a closed case has no stage to be in and every
    // panel below writes. Five disabled buttons where the honest answer is one
    // sentence is worse than the sentence.
    await renderPage()
    expect(document.querySelector('.stepper')).toBeNull()
    expect(screen.queryByRole('button', { name: /Validate/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Send/i })).toBeNull()
  })

  it('offers neither Close nor Restart', async () => {
    await renderPage()
    expect(screen.queryByRole('button', { name: 'Close case' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Restart/ })).toBeNull()
  })

  it('still shows the badges and the way back to the record', async () => {
    // Closing ends the WORK, not the record.
    await renderPage()
    const strip = document.querySelector('.live-strip')
    expect(within(strip).getByText('Closed')).toBeInTheDocument()
    expect(within(strip).getByText('Validated by CR')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Company profile' })).toBeInTheDocument()
  })

  it('renders a reason containing markup as text, not as markup', async () => {
    routeGet(caseAt({ ...CLOSED, closed_reason: '<img src=x onerror=alert(1)>' }))
    await renderPage()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('.closed-why img')).toBeNull()
  })
})
