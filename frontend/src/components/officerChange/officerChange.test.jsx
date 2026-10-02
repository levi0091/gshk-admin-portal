import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CessationDrawer from './CessationDrawer.jsx'
import AppointmentDrawer from './AppointmentDrawer.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import StageDataVerification from './StageDataVerification.jsx'
import StageSigning from './StageSigning.jsx'
import StageSubmission from './StageSubmission.jsx'
import StageCrStatus from './StageCrStatus.jsx'
import StageConfirmation from './StageConfirmation.jsx'
import StageClientVerification from './StageClientVerification.jsx'
import { stageIndexFor, stageDone, deadlineText } from './workflow.js'

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn(); const upload = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: vi.fn(), upload: (...a) => upload(...a), blob: vi.fn(() => Promise.resolve(new Blob())),
    put: vi.fn(),
  },
}))

const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }
const BASE = {
  id: 'k1', case_no: 'ND2A-2026-0001', form_code: 'Nd2a', case_type: 'ND2A', editable: true,
  officers: [
    { officer_id: 'o1', role: 'director', party_type: 'individual', name: 'CHAN Tai Man', pending: false },
    { officer_id: 'o2', role: 'director', party_type: 'individual', name: 'LEE Dead', pending: false,
      date_of_death: '2026-09-20' },
    { officer_id: 'o3', role: 'company_secretary', party_type: 'corporate', name: 'GSHK Ltd', pending: false },
  ],
  entries: [], route: { esign_available: true, reasons: [], consents: [] },
  signatory: { name: 'GSHK Ltd', capacities: ['Director of the Company Secretary (Body Corporate)'] },
  client_approved: true,
}
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  // The appointment drawer reads /lookups for CR's country and district lists.
  get.mockResolvedValue({})
})

describe('workflow', () => {
  it('derives the stage from the case for both routes', () => {
    expect(stageIndexFor({ client_approved: null })).toBe(1)
    expect(stageIndexFor({ client_approved: true })).toBe(2)
    expect(stageIndexFor({ client_approved: true, filing: { stage: 'validated' } })).toBe(3)
    expect(stageIndexFor({ client_approved: true, filing: { stage: 'signed' } })).toBe(4)
    expect(stageIndexFor({ client_approved: true, signing_method: 'manual', data_checked_at: 'x' })).toBe(3)
    expect(stageIndexFor({ client_approved: true, signing_method: 'manual', data_checked_at: 'x',
      manual_signed_document_id: 'd' })).toBe(4)
    // Filed opens CR Status even before CR has listed it — "Check now" lives there.
    expect(stageIndexFor({ manual_receipt: { caseNo: '1' }, cr_status: { code: 'cr_not_checked' } })).toBe(6)
    expect(stageDone({ manual_receipt: { caseNo: '1' }, cr_status: { code: 'cr_pending' } }, 5)).toBe(true)
    expect(stageDone({ manual_receipt: { caseNo: '1' }, cr_status: { code: 'cr_pending' } }, 6)).toBe(false)
    expect(stageDone({ manual_receipt: { caseNo: '1' }, cr_status: { code: 'cr_registered' } }, 6)).toBe(true)
    expect(stageIndexFor({ changes_applied_at: 'x', cr_status: { code: 'cr_pending' } })).toBe(6)
    expect(stageIndexFor({ closed_at: 'x' })).toBe(0)
    expect(stageDone({ client_approved: true }, 1)).toBe(true)
  })

  it('words the deadline', () => {
    expect(deadlineText({ date: 'x', days: -2 })).toEqual({ text: '2 days overdue', overdue: true })
    expect(deadlineText({ date: 'x', days: 1 }).text).toBe('Due in 1 day')
    expect(deadlineText(null)).toBeNull()
  })
})

describe('CessationDrawer', () => {
  it('asks a person for the reason, pre-set from a date of death', async () => {
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o2')
    expect(screen.getByLabelText('Deceased')).toBeChecked()
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o1')
    expect(screen.getByLabelText('Resignation / Others')).toBeChecked()
  })

  it('asks a body corporate for no reason, and saves the cessation', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const saved = vi.fn()
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={saved} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o3')
    expect(screen.queryByLabelText('Deceased')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Date of cessation/), '2026-09-28')
    await userEvent.click(screen.getByRole('button', { name: 'Add cessation' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries',
      { kind: 'cessation', officer_id: 'o3', effective_date: '2026-09-28' }))
    expect(saved).toHaveBeenCalled()
  })
})

describe('CessationDrawer — the secretary register', () => {
  const data = { ...BASE, officers: [
    ...BASE.officers.slice(0, 2),
    { officer_id: null, secretary_id: 'S1', register_only: true, role: 'company_secretary',
      party_type: 'corporate', name: 'Get Started HK Limited', pending: false, secretary_ids: ['S1'] },
  ] }

  it('ceases a register-only secretary by its register id, and says it will be recorded', async () => {
    post.mockResolvedValue({ id: 'k1' })
    wrap(<CessationDrawer data={data} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'cs:S1')
    expect(screen.getByText(/Held on the secretary register only/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Date of cessation/), '2026-09-28')
    await userEvent.click(screen.getByRole('button', { name: 'Add cessation' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries',
      { kind: 'cessation', secretary_id: 'S1', effective_date: '2026-09-28' }))
  })

  it('opens on the officer pressed on the profile, including a register id with an officer twin', () => {
    const twinned = { ...BASE, officers: [...BASE.officers.slice(0, 2),
      { ...BASE.officers[2], secretary_ids: ['S7'] }] }
    wrap(<CessationDrawer data={twinned} preselect="cs:S7" onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByLabelText(/Officer/)).toHaveValue('o3')
  })

  it('pre-sets the reason from a date of death when opened on that officer', () => {
    wrap(<CessationDrawer data={BASE} preselect="o2" onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByLabelText('Deceased')).toBeChecked()
  })
})

describe('AppointmentDrawer', () => {
  const entry = { id: 'n2', kind: 'appointment', party_type: 'individual', person_id: 'p9',
    capacity: 'director', effective_date: '2026-09-29', party: { name: 'HO New' },
    correspondence_same_as_residential: true }

  it('shows the correspondence boxes only when the tick is cleared', async () => {
    wrap(<AppointmentDrawer data={BASE} entry={entry} onClose={() => {}} onSaved={() => {}} />)
    const tick = screen.getByLabelText(/Correspondence address is the same as the residential address/)
    expect(tick).toBeChecked()
    expect(screen.queryByTestId('corr-address')).not.toBeInTheDocument()
    await userEvent.click(tick)
    expect(screen.getByTestId('corr-address')).toBeInTheDocument()
  })

  it('asks the Section 5 question for a natural-person secretary only', async () => {
    wrap(<AppointmentDrawer data={BASE} entry={entry} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.queryByLabelText(/ordinarily resides in Hong Kong/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Company Secretary'))
    expect(screen.getByLabelText(/ordinarily resides in Hong Kong/)).toBeInTheDocument()
  })

  it('asks who signs a body corporate director\'s consent', async () => {
    const corp = { ...entry, party_type: 'corporate', corporate_entity_id: 'c9', person_id: null,
      party: { name: 'Corp Ltd' } }
    wrap(<AppointmentDrawer data={BASE} entry={corp} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByLabelText(/Consent signed by/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Correspondence address/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Alternate/)).not.toBeInTheDocument()
  })
})

describe('ParticularsChangeCard', () => {
  it('asks before omitting a line', async () => {
    patch.mockResolvedValue({ id: 'k1' })
    const data = { ...BASE, form_code: 'Nd2b', entries: [{ id: 'n3', kind: 'change', officer_id: 'o1',
      capacity: 'director', party: { name: 'CHAN Tai Man' }, items: [
        { key: 'email', cr_item: 'f', label: 'Email address', old_text: 'a', new_text: 'b',
          effective_date: null, omitted: false }] }] }
    wrap(<ParticularsChangeCard data={data} reload={vi.fn()} can={ALL} />)
    await userEvent.click(screen.getByRole('button', { name: 'Omit' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/stays pending/)
    expect(patch).not.toHaveBeenCalled()
    await userEvent.click(screen.getAllByRole('button', { name: 'Omit' }).at(-1))
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1/entries/n3',
      { items: [{ key: 'email', omitted: true }] })
  })
})

describe('StageDataVerification', () => {
  it('disables e-Sign and names who has no e-Registry account', () => {
    const data = { ...BASE, route: { esign_available: false, consents: [],
      reasons: ['HO New has no e-Registry account stored on their profile'] } }
    wrap(<StageDataVerification data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByLabelText(/e-Sign via CR/)).toBeDisabled()
    expect(screen.getByText(/HO New has no e-Registry account/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark as checked' })).toBeInTheDocument()
  })
})

describe('StageSigning', () => {
  const manual = { ...BASE, signing_method: 'manual', data_checked_at: 'x' }

  it('offers no download for a manual ND2A, and one for a manual ND2B', () => {
    const { unmount } = wrap(<StageSigning data={manual} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Download form' })).not.toBeInTheDocument()
    expect(screen.getByText(/Prepare the ND2A on the Companies Registry's portal/)).toBeInTheDocument()
    unmount()
    wrap(<StageSigning data={{ ...manual, form_code: 'Nd2b' }} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Download form' })).toBeInTheDocument()
  })

  it('does not move on after the upload; Continue does', async () => {
    const goTo = vi.fn()
    upload.mockResolvedValue({ ...manual, manual_signed_document_id: 'd1' })
    const reload = vi.fn()
    const { rerender } = wrap(<StageSigning data={manual} reload={reload} can={ALL} goTo={goTo} />)
    await userEvent.upload(screen.getByLabelText(/Signed form/), new File(['%PDF'], 's.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload signed form' }))
    await waitFor(() => expect(reload).toHaveBeenCalled())
    expect(goTo).not.toHaveBeenCalled()
    rerender(<MemoryRouter><StageSigning data={{ ...manual, manual_signed_document_id: 'd1' }}
                                         reload={reload} can={ALL} goTo={goTo} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: /Continue to Submission/ }))
    expect(goTo).toHaveBeenCalledWith(4)
  })

  it('e-Sign applies the signatures with one press and no password field', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'validated' },
      route: { consents: [{ entry_id: 'n2', signer_name: 'HO New', eservice_user_id: 'ER9' }] } }
    wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/HO New/)).toBeInTheDocument()
    expect(document.querySelector('input[type="password"]')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Apply signatures' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/sign', {})
  })
})

describe('StageSubmission', () => {
  it('needs the CR case number, the date and the receipt before recording', async () => {
    const data = { ...BASE, signing_method: 'manual', manual_signed_document_id: 'd1',
      profile_changes: [{ entry_id: 'n1', text: 'Mark CHAN as a former director' }], documents: [] }
    wrap(<StageSubmission data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    const record = screen.getByRole('button', { name: 'Record filing' })
    expect(record).toBeDisabled()
    expect(screen.getByText(/Mark CHAN as a former director/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/CR case number/), '123456')
    await userEvent.type(screen.getByLabelText(/Transaction date/), '2026-09-30')
    expect(record).toBeDisabled()
    await userEvent.upload(screen.getByLabelText(/CR receipt/), new File(['%PDF'], 'r.pdf', { type: 'application/pdf' }))
    expect(record).toBeEnabled()
  })

  it('shows a write-back problem as a warning on a filed case', async () => {
    post.mockResolvedValue({ id: 'k1', write_back: { errors: ['HO New: timeout'] }, documents_filed: [] })
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'signed' },
      profile_changes: [], documents: [] }
    wrap(<StageSubmission data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    await userEvent.click(screen.getByLabelText(/Filing it with the Companies Registry cannot be undone/))
    await userEvent.click(screen.getByRole('button', { name: 'File ND2A with CR' }))
    // Preview, tick, then a confirmation — the portal's rule for submitForm.
    expect(post).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'File with CR' }))
    expect(await screen.findByText(/Filed with CR — but some follow-up did not complete/)).toBeInTheDocument()
    expect(screen.getByText('HO New: timeout')).toBeInTheDocument()
  })

  it('shows the form as it will be filed before an e-Sign filing', () => {
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'signed' },
      profile_changes: [], documents: [] }
    wrap(<StageSubmission data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/the Companies Registry validated and that has been signed/))
      .toBeInTheDocument()
  })

  it('draws no filing controls for a role without File with CR — not even disabled', () => {
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'signed' },
      profile_changes: [], documents: [] }
    wrap(<StageSubmission data={data} reload={vi.fn()} can={{ ...ALL, tpsiSubmit: false }}
                          goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /File ND2A with CR/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.getByText(/Filing needs Companies Registry filing/)).toBeInTheDocument()
  })
})

describe('the case stages draw nothing a role may not use (#21)', () => {
  const READER = { write: false, tpsiWrite: false, tpsiSubmit: false, tpsiRead: false }

  it('Data Verification: no KYC tick, capacity picker, route radios or step buttons', () => {
    const data = { ...BASE, entries: [{ id: 'n2', kind: 'appointment', party: { name: 'HO New' },
      kyc_cleared: true, documents: [] }], signatory: { capacities: ['Director'] },
      // KYC is now one of Data Verification's manual checks (Jacqueline A4).
      manual_checks: [{ code: 'kyc', entry_id: 'n2', label: 'KYC / WorldCheck cleared — HO New',
        kind: 'tick', ok: true, document: null }] }
    wrap(<StageDataVerification data={data} reload={vi.fn()} can={READER} goTo={vi.fn()} />)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Validate|Mark as checked/ })).not.toBeInTheDocument()
    expect(screen.getByText('KYC / WorldCheck cleared — HO New').closest('[data-check]'))
      .toHaveAttribute('data-ok', 'true')
    expect(screen.queryAllByRole('button').filter(b => b.disabled)).toEqual([])
  })

  it('Signing and CR Status: no Apply signatures, no Check now', () => {
    const esign = { ...BASE, signing_method: 'esign', filing: { stage: 'validated' },
      route: { consents: [] } }
    const { unmount } = wrap(<StageSigning data={esign} reload={vi.fn()} can={READER} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Apply signatures' })).not.toBeInTheDocument()
    unmount()
    wrap(<StageCrStatus data={{ ...BASE, cr_status: { code: 'cr_pending', label: 'Pending' } }}
                        reload={vi.fn()} can={READER} />)
    expect(screen.queryByRole('button', { name: 'Check now' })).not.toBeInTheDocument()
  })

  it("CR Status prints CR's own words, on the badge when the answer is unknown", () => {
    wrap(<StageCrStatus data={{ ...BASE, cr_status: { code: 'cr_unknown', label: 'Other CR status',
      cr_text: 'Withdrawn by presenter' } }} reload={vi.fn()} can={ALL} />)
    expect(screen.getAllByText(/Withdrawn by presenter/).length).toBeGreaterThan(1)
  })
})

describe('StageConfirmation — an unfinished profile update', () => {
  const filed = { ...BASE, manual_receipt: { caseNo: '123456' }, profile_changes: [],
    documents: [], applied_at: null }

  it('says the update did not finish and offers to finish it', async () => {
    post.mockResolvedValue({ ...filed, applied_at: 'x', write_back: { errors: [] } })
    const reload = vi.fn()
    wrap(<StageConfirmation data={filed} reload={reload} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/The profile update did not finish/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Finish the profile update' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/apply', { confirm: true })
    await waitFor(() => expect(reload).toHaveBeenCalled())
  })

  it("shows a free form's receipt as CR TEST returned it: barcode reference, filing time", () => {
    const esign = { ...BASE, signing_method: 'esign', applied_at: 'x', profile_changes: [],
      documents: [], filing: { stage: 'submitted', submitted_at: '2026-10-02T07:05:00Z' },
      receipt: { caseNo: '141946253', docCodesWithBarcode: 'ND2B (T0022892651)',
        documentRefNo: 'T0022892651', transactionDate: null, refNo: null } }
    wrap(<StageConfirmation data={esign} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText('141946253')).toBeInTheDocument()
    expect(screen.getByText('T0022892651')).toBeInTheDocument()
    expect(screen.getByText('Filed')).toBeInTheDocument()
  })

  it('offers nothing once the update is complete, or undone after a rejection', () => {
    const { unmount } = wrap(<StageConfirmation data={{ ...filed, applied_at: 'x' }}
                                                reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByText(/did not finish/)).not.toBeInTheDocument()
    unmount()
    wrap(<StageConfirmation data={{ ...filed, undone_at: 'y' }} reload={vi.fn()} can={ALL}
                            goTo={vi.fn()} />)
    expect(screen.queryByText(/did not finish/)).not.toBeInTheDocument()
  })
})

describe('ParticularsChangeCard — the secretary register (#19)', () => {
  it('adds a register-only secretary by its register id', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const data = { ...BASE, form_code: 'Nd2b', entries: [], officers: [
      { officer_id: null, secretary_id: 'S1', register_only: true, role: 'company_secretary',
        name: 'Get Started HK Limited', pending: false }] }
    wrap(<ParticularsChangeCard data={data} reload={vi.fn()} can={ALL} />)
    await userEvent.selectOptions(screen.getByLabelText('Officer to add'), 'cs:S1')
    await userEvent.click(screen.getByRole('button', { name: 'Add officer' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries',
      { kind: 'change', secretary_id: 'S1' })
  })
})

describe('StageCrStatus', () => {
  it('offers Undo only on a rejection with changes applied', () => {
    const { unmount } = wrap(<StageCrStatus data={{ ...BASE, cr_status: { code: 'cr_pending', label: 'Pending at CR' },
      applied_at: 'x' }} reload={vi.fn()} can={ALL} />)
    expect(screen.queryByRole('button', { name: 'Undo profile update' })).not.toBeInTheDocument()
    unmount()
    wrap(<StageCrStatus data={{ ...BASE, cr_status: { code: 'cr_rejected', label: 'Rejected by CR' },
      applied_at: 'x' }} reload={vi.fn()} can={ALL} />)
    expect(screen.getByRole('button', { name: 'Undo profile update' })).toBeInTheDocument()
  })
})

describe('StageClientVerification — the revision the client holds (migration 051)', () => {
  const stage = over => wrap(
    <StageClientVerification data={{ ...BASE, client_approved: null, ...over }}
                             reload={vi.fn()} can={ALL} goTo={vi.fn()} />)

  it('a resend reads "Rev. 2 sent", matching the [Rev. 2] in the client\'s inbox', () => {
    stage({ verification_sent_at: '2026-10-01T02:00:00Z', verification_revision: 2 })
    expect(screen.getByText(/Rev\. 2 sent/)).toBeInTheDocument()
  })

  it('the first email is unmarked, as it is in the client\'s inbox', () => {
    stage({ verification_sent_at: '2026-10-01T02:00:00Z', verification_revision: 1 })
    expect(screen.queryByText(/Rev\. \d/)).not.toBeInTheDocument()
  })

  it('after a restart, says the next send is Rev. 2 and the earlier link dies', () => {
    // Restart cleared verification_sent_at; the client still has the first email.
    stage({ verification_sent_at: null, verification_revision: 1 })
    expect(screen.getByText(/This goes out as Rev\. 2, and the Confirm link in the\s+earlier email stops working/))
      .toBeInTheDocument()
  })

  it('a first send promises no revision', () => {
    stage({ verification_sent_at: null, verification_revision: 0 })
    expect(screen.queryByText(/goes out as Rev\./)).not.toBeInTheDocument()
  })
})
