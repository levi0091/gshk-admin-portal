/**
 * NOT a test — a visual harness. Renders each workflow stage with the real
 * components and dumps the markup so it can be screenshotted against the real
 * stylesheet (see scripts/shoot-stages.mjs). Reading JSX tells you what you
 * wrote; a picture tells you what an operator sees.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

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
vi.mock('../../context/AuthContext.jsx', () => ({
  useAuth: () => ({ isTestEnv: true, profile: { email: 'levi@zenexflow.com' } }),
}))

const OUT = path.resolve(process.cwd(), '.visual')

const CASE = {
  id: 'c1', entity_id: 'e7', case_no: 'NAR-2026-0041', filing_id: 'f1',
  company_name: 'Skyline Capital Management Limited', br_number: '76543210',
  signing_method: 'esign', aml_cleared: true, accounts_ready: true,
  validated_at: '2026-08-30T06:22:00Z',
  verification_sent_at: '2026-08-30T06:31:00Z',
  client_response_at: '2026-08-30T07:02:00Z', client_approved: true,
  form_status: { code: 'validated', label: 'Validated by CR', failed: false, faults: [] },
  receipt: {
    caseNo: '141945492', brNo: '76543210',
    engCoyName: 'Skyline Capital Management Limited',
    pymtNo: 'P8891201', pymtRefNo: 'REF-2026-88431',
    transactionDate: '30/08/2026', transactionTime: '14:39',
    pymtMtd: 'Deposit account', totalAmount: '2610.00',
    paymentRcptList: [
      { rcptNo: 'D77000418931', revCode: 'R1', docShtFrm: 'NAR1', amtChrg: '2610.00' },
    ],
  },
}

beforeEach(() => {
  get.mockImplementation(url => {
    const u = String(url)
    if (u.includes('/return-data')) {
      return Promise.resolve({
        year: 2026, company_name: 'Skyline Capital Management Limited',
        br_number: '76543210', registered_office: 'Unit 2201, 22/F, Tower One, Admiralty Centre, HK',
        directors: ['Chan Tai Man', 'Wong Mei Ling'],
        secretaries: ['Get Started HK Limited'],
        signatory: { name: 'Get Started HK Limited', capacity: '', person_id: null },
        signatory_capacity: null,
        signatory_capacity_options: ['Authorized Representative of the Company Secretary (Body Corporate)'],
        member_count: 2,
        share_classes: [{ name: 'Ordinary', total_issued: 100, currency: 'HKD' }],
        problems: [],
      })
    }
    if (u.includes('/verification/recipients')) {
      return Promise.resolve({
        recipients: [
          { person_id: 'p1', name: 'CHAN TAI MAN', email: 'chan@skylinecapital.hk',
            role: 'director', party_type: 'individual', reason: null },
          { person_id: 'p2', name: 'WONG MEI LING', email: 'wong@skylinecapital.hk',
            role: 'director', party_type: 'individual', reason: null },
          { person_id: null, name: 'HOLDCO LIMITED', email: null, role: 'director',
            party_type: 'corporate',
            reason: 'a corporate director has no address on record' },
        ],
        default_to: ['chan@skylinecapital.hk', 'wong@skylinecapital.hk'],
        max_recipients: 20,
      })
    }
    if (u.includes('/summary')) {
      return Promise.resolve({
        form_code: 'Nar1', stage: 'signed', has_schedule_1: true,
        company_name: 'Skyline Capital Management Limited', br_number: '76543210',
        year: '2026', registered_office: 'Unit 2201, 22/F, Tower One, Admiralty Centre, HK',
        directors: ['CHAN, TAI MAN', 'WONG, MEI LING'],
        secretaries: ['Get Started HK Limited'],
        share_classes: [{ name: 'Ordinary', currency: 'HKD', total_issued: '100' }],
        member_count: 2, members: ['CHAN, TAI MAN', 'WONG, MEI LING'],
        signatory: {
          name: 'Get Started HK Limited', date: '30/08/2026',
          capacity: 'Authorized Representative of the Company Secretary (Body Corporate)',
        },
        signed_at: '2026-08-30T07:36:00Z',
      })
    }
    if (u.includes('/tpsi/credentials')) {
      return Promise.resolve({
        eservice_user_id: 'GSHKPN02', has_eservice_password: true,
        tpsi_password_expires_at: new Date(Date.now() + 12 * 86400000).toISOString(),
      })
    }
    if (u.includes('/doc-status')) {
      return Promise.resolve([{ documentName: 'NAR1 Annual Return',
                                documentStatus: 'Registered',
                                submissionDate: '30/08/2026' }])
    }
    return Promise.resolve({
      fee: '2610.00', max_fee: '3480.00', fee_is_certain: true,
      on_time_fee: '105.00', balance: '12480', sufficient: true,
      fee_detail: { band: 'more than 6 months but within 9 months after the return date',
                    return_date: '12/03/2026' },
    })
  })
  post.mockResolvedValue({}); patch.mockResolvedValue({}); upload.mockResolvedValue({})
  blob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
  global.URL.createObjectURL = vi.fn(() => 'about:blank')
  global.URL.revokeObjectURL = vi.fn()
})

const noop = () => {}
const SHOOT = process.env.SHOOT === '1'

async function dump(name, ui, settle) {
  const { container } = render(<MemoryRouter>{ui}</MemoryRouter>)
  if (settle) await settle()
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), container.innerHTML, 'utf8')
}

describe.runIf(SHOOT)('visual harness', () => {
  it('1 · Data Verification', async () => {
    await dump('1-data-verification',
      <StageDataVerification caseRow={{ ...CASE, form_status: { code: 'draft' }, filing_id: null }}
                             canWrite canValidate onChanged={noop} onError={noop} onGo={noop} />,
      () => waitFor(() => screen.getByText(/freezes an immutable snapshot/)))
  })

  it('2 · Client Verification', async () => {
    await dump('2-client-verification',
      <StageClientVerification caseRow={CASE} canWrite onChanged={noop} onError={noop} />,
      () => waitFor(() => screen.getByText('Form NAR1 + Schedule 1')))
  })

  it('3 · Signing', async () => {
    await dump('3-signing',
      <StageSigning caseRow={CASE} canWrite onChanged={noop} onError={noop} onGo={noop} />,
      () => waitFor(() => screen.getByText(/Deposit balance/)))
  })

  it('3b · Signing — manual', async () => {
    await dump('3b-signing-manual',
      <StageSigning caseRow={{ ...CASE, signing_method: 'manual' }} canWrite
                    onChanged={noop} onError={noop} onGo={noop} />,
      () => waitFor(() => screen.getByText(/Choose the signed PDF/)))
  })

  it('4 · Submission', async () => {
    await dump('4-submission',
      <StageSubmission caseRow={{ ...CASE, form_status: { code: 'signed', label: 'Signed' } }}
                       canSubmit onChanged={noop} onError={noop} onGo={noop} />,
      () => waitFor(() => screen.getByText(/Irreversible action/)))
  })

  it('5 · Confirmation', async () => {
    await dump('5-confirmation',
      <StageConfirmation caseRow={{ ...CASE, form_status: { code: 'registered', label: 'Registered' } }}
                         canRead onError={noop} />,
      () => waitFor(() => screen.getByText(/filed & confirmed by CR/)))
  })
})
