import { useState } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CessationDrawer from './CessationDrawer.jsx'
import AppointmentDrawer from './AppointmentDrawer.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import StageDataVerification from './StageDataVerification.jsx'
import StageSigning from './StageSigning.jsx'
import StageSubmission from './StageSubmission.jsx'
import StageConfirmation from './StageConfirmation.jsx'
import StageClientVerification from './StageClientVerification.jsx'
import { STAGES, stageIndexFor, stageDone, deadlineText } from './workflow.js'

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
    // Filed is the last stage, Confirmation, all five ticked (Levi 2026-10-17:
    // there is no CR Status stage after it).
    expect(stageIndexFor({ manual_receipt: { caseNo: '1' } })).toBe(5)
    expect(stageIndexFor({ changes_applied_at: 'x' })).toBe(5)
    for (const n of [1, 2, 3, 4, 5]) {
      expect(stageDone({ manual_receipt: { caseNo: '1' } }, n), `stage ${n}`).toBe(true)
    }
    expect(STAGES).toEqual(['Client Verification', 'Data Verification', 'Signing',
      'Submission', 'Confirmation'])
    // A legacy `registered` filing (until migration 054 runs) is filed too.
    expect(stageIndexFor({ client_approved: true, filing: { stage: 'registered' } })).toBe(5)
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

describe('ParticularsChangeCard — Data maintenance (Levi 2026-10-29)', () => {
  const item = (key, label) => ({ key, cr_item: 'f', label, old_text: 'a', new_text: 'b',
    effective_date: null, omitted: false })
  const ND2B = (items = [item('email', 'Email address'), item('name_en', 'Name in English')]) => ({
    ...BASE, form_code: 'Nd2b', company_name: 'Skyline Capital Limited',
    entries: [{ id: 'n3', kind: 'change', officer_id: 'o1', capacity: 'director',
      party: { name: 'CHAN Tai Man' }, items }] })

  /** reload() swaps in whatever the endpoint returned, as the page does. */
  function Harness({ first, then }) {
    const [data, setData] = useState(first)
    return <ParticularsChangeCard data={data} can={ALL}
                                  reload={async next => setData(next || then)} />
  }
  const removeEmail = data => ({ ...data, entries: [{ ...data.entries[0],
    items: data.entries[0].items.filter(i => i.key !== 'email') }] })

  it('settles one line: confirms by name, calls the endpoint, and the line is gone', async () => {
    const first = ND2B()
    post.mockResolvedValue(removeEmail(first))
    wrap(<Harness first={first} />)
    await userEvent.click(screen.getByRole('button', { name: 'Data maintenance — Email address' }))
    const dialog = screen.getByRole('alertdialog')
    // It names what is lost, and says CR is not told.
    expect(dialog).toHaveTextContent(/Treat "Email address" as data maintenance\?/)
    expect(dialog).toHaveTextContent(/stop reporting this difference for CHAN Tai Man at Skyline Capital Limited/)
    expect(dialog).toHaveTextContent(/CR will not be told/)
    expect(post).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Data maintenance' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries/n3/items/email/maintenance', {})
    await waitFor(() => expect(screen.queryByText('Email address', { exact: false })).not.toBeInTheDocument())
    // The other pending line on the same officer is untouched.
    expect(screen.getByText(/Name in English/)).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('does nothing on Cancel', async () => {
    wrap(<Harness first={ND2B()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Data maintenance — Email address' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
    expect(post).not.toHaveBeenCalled()
    expect(patch).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(screen.getByText(/Email address/)).toBeInTheDocument()
  })

  it('is offered only while the case is editable and the role may write', () => {
    const { unmount } = wrap(<ParticularsChangeCard data={{ ...ND2B(), editable: false }}
                                                    reload={vi.fn()} can={ALL} />)
    expect(screen.queryByRole('button', { name: /Data maintenance/ })).not.toBeInTheDocument()
    unmount()
    wrap(<ParticularsChangeCard data={ND2B()} reload={vi.fn()} can={{ ...ALL, write: false }} />)
    expect(screen.queryByRole('button', { name: /Data maintenance/ })).not.toBeInTheDocument()
  })

  it('says a correspondence address stays pending when the residential one is settled', async () => {
    wrap(<Harness first={ND2B([item('residential_address', 'Residential address')])} />)
    await userEvent.click(screen.getByRole('button', { name: 'Data maintenance — Residential address' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/correspondence address that differs stays pending/)
  })

  it('shows the refusal if the endpoint refuses, and leaves the line', async () => {
    post.mockRejectedValue(Object.assign(new Error('This case is closed.'), { status: 409 }))
    wrap(<Harness first={ND2B()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Data maintenance — Email address' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Data maintenance' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/closed/)
    expect(screen.getByText(/Email address/)).toBeInTheDocument()
  })
})

describe('StageDataVerification', () => {
  const NO_CARD = [
    { code: 'kyc', entry_id: 'n2', label: 'KYC / WorldCheck cleared — HO New', kind: 'tick', ok: true },
  ]
  const WITH_ENTRIES = { ...BASE, manual_checks: NO_CARD, entries: [
    { id: 'n1', kind: 'cessation', party: { name: 'CHAN Tai Man' }, summary: 'Director · ceases' },
    { id: 'n2', kind: 'appointment', party: { name: 'HO New', profile_path: '/persons/p9' },
      summary: 'Director · appointed', eservice: { configured: false, has_password: false } }] }

  it('has no resignation-letter row, no "Officers on this form" card, and keeps the KYC tick', () => {
    wrap(<StageDataVerification data={WITH_ENTRIES} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByText(/Resignation letter/)).not.toBeInTheDocument()
    expect(screen.queryByText('Officers on this form')).not.toBeInTheDocument()
    expect(screen.queryByText(/Supporting documents/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Choose file|Attach a file/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('KYC / WorldCheck cleared — HO New')).toBeInTheDocument()
  })

  it('does not hold a leaver back for a letter: with the KYC ticked the form can be checked', () => {
    wrap(<StageDataVerification data={{ ...WITH_ENTRIES, signing_method: 'manual' }}
                                reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Mark as checked' })).toBeEnabled()
  })

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

  describe('the e-Registry hint, moved here from Data Verification (Levi 2026-10-29)', () => {
    const entries = [
      { id: 'n2', kind: 'appointment', party: { name: 'HO New', profile_path: '/persons/p9' },
        eservice: { configured: true, has_password: true, eservice_user_id: 'ER9' } },
      { id: 'n4', kind: 'appointment', party: { name: 'LAM Missing', profile_path: '/persons/p4' },
        eservice: { configured: false, has_password: false } },
      { id: 'n1', kind: 'cessation', party: { name: 'CHAN Tai Man' } },
    ]

    it('on e-Sign, says the client signs nothing for a director with an account', () => {
      const data = { ...BASE, entries, signing_method: 'esign', filing: { stage: 'validated' } }
      wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
      const hint = screen.getByTestId('eregistry-hints')
      expect(within(hint).getByText(/set up with them \(ER9\)\. The client signs nothing/)).toBeInTheDocument()
      // A leaver carries no e-Registry block, so no line.
      expect(within(hint).queryByText(/CHAN Tai Man/)).not.toBeInTheDocument()
    })

    it('on the manual route, names the director with no account and links the profile', () => {
      wrap(<StageSigning data={{ ...BASE, entries, signing_method: 'manual', data_checked_at: 'x' }}
                         reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
      const hint = screen.getByTestId('eregistry-hints')
      expect(within(hint).getByText(/can only be filed on the manual route/)).toBeInTheDocument()
      expect(within(hint).getByRole('link', { name: 'Add it on the profile' }))
        .toHaveAttribute('href', '/persons/p4')
      // The stored account is not used on this route, so it is not promised.
      expect(within(hint).queryByText(/GSHK applies this director's consent/)).not.toBeInTheDocument()
    })

    it('draws nothing when no entry carries an e-Registry block', () => {
      wrap(<StageSigning data={{ ...BASE, entries: [entries[2]], signing_method: 'manual', data_checked_at: 'x' }}
                         reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
      expect(screen.queryByTestId('eregistry-hints')).not.toBeInTheDocument()
    })
  })

  it('e-Sign applies the signatures with one press and no password field', async () => {
    post.mockResolvedValue({ id: 'k1' })
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'validated' },
      route: { consents: [{ entry_id: 'n2', signer_name: 'HO New', eservice_user_id: 'ER9' }] } }
    wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText(/HO New/)).toBeInTheDocument()
    expect(document.querySelector('input[type="password"]')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Apply consent signature' }))
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

  it('Signing: no Apply signatures; Confirmation: no Undo', () => {
    const esign = { ...BASE, signing_method: 'esign', filing: { stage: 'validated' },
      route: { consents: [] } }
    const { unmount } = wrap(<StageSigning data={esign} reload={vi.fn()} can={READER} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Apply signatures' })).not.toBeInTheDocument()
    unmount()
    wrap(<StageConfirmation data={{ ...BASE, manual_receipt: { caseNo: '1' }, applied_at: 'x',
      profile_changes: [], documents: [] }} reload={vi.fn()} can={READER} />)
    expect(screen.queryByRole('button', { name: /Undo profile update/ })).not.toBeInTheDocument()
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

  it('offers no way on to a stage after it — it is the last one', () => {
    wrap(<StageConfirmation data={{ ...filed, applied_at: 'x' }} reload={vi.fn()} can={ALL} />)
    expect(screen.queryByRole('button', { name: /CR Status/ })).not.toBeInTheDocument()
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

describe('StageConfirmation — Undo after CR rejects the change', () => {
  // The portal no longer asks CR (Levi 2026-10-17), so the operator records
  // the rejection CR sent them; the button lives on the last stage.
  const filed = { ...BASE, manual_receipt: { caseNo: '1' }, applied_at: 'x',
    profile_changes: [], documents: [] }

  it('offers Undo on a filed case with changes applied, and says what it records', async () => {
    post.mockResolvedValue({ ...filed, undone_at: 'z' })
    const reload = vi.fn()
    wrap(<StageConfirmation data={filed} reload={reload} can={ALL} />)
    await userEvent.click(screen.getByRole('button', { name: 'CR rejected it — undo profile update' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Undo profile update' })
    expect(within(dialog).getByText(/Companies Registry rejected/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Undo profile update' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/undo', { confirm: true })
    await waitFor(() => expect(reload).toHaveBeenCalled())
  })

  it('offers no Undo with nothing applied, once undone, or without File with CR', () => {
    const { unmount } = wrap(<StageConfirmation data={{ ...filed, applied_at: null, entries: [] }}
                                                reload={vi.fn()} can={ALL} />)
    expect(screen.queryByRole('button', { name: /undo profile update/ })).not.toBeInTheDocument()
    unmount()
    const again = wrap(<StageConfirmation data={{ ...filed, undone_at: 'y' }} reload={vi.fn()} can={ALL} />)
    expect(screen.queryByRole('button', { name: /undo profile update/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Profile update undone/)).toBeInTheDocument()
    again.unmount()
    wrap(<StageConfirmation data={filed} reload={vi.fn()} can={{ ...ALL, tpsiSubmit: false }} />)
    expect(screen.queryByRole('button', { name: /undo profile update/ })).not.toBeInTheDocument()
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

// -- Levi 2026-10-18 -----------------------------------------------------------------

describe('CessationDrawer — the date of death', () => {
  it('asks for it on a death, pre-filled from the profile, and sends it', async () => {
    post.mockResolvedValue({ id: 'k1' })
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o2')
    expect(screen.getByLabelText(/Date of death/)).toHaveValue('2026-09-20')
    // A person ceases on the day they die, so the cessation date follows.
    expect(screen.getByLabelText(/Date of cessation/)).toHaveValue('2026-09-20')
    expect(screen.getByText(/saved to LEE Dead's profile once the form is filed/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add cessation' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries', {
      kind: 'cessation', officer_id: 'o2', effective_date: '2026-09-20',
      cessation_reason: 'D', date_of_death: '2026-09-20' }))
  })

  it('cannot add a death without its date', async () => {
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o1')
    expect(screen.queryByLabelText(/Date of death/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Deceased'))
    const add = screen.getByRole('button', { name: 'Add cessation' })
    expect(add).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Date of death/), '2026-09-18')
    expect(screen.getByLabelText(/Date of cessation/)).toHaveValue('2026-09-18')
    expect(add).toBeEnabled()
  })

  it('leaves a cessation date the operator typed alone', async () => {
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o1')
    await userEvent.type(screen.getByLabelText(/Date of cessation/), '2026-09-25')
    await userEvent.click(screen.getByLabelText('Deceased'))
    await userEvent.type(screen.getByLabelText(/Date of death/), '2026-09-18')
    expect(screen.getByLabelText(/Date of cessation/)).toHaveValue('2026-09-25')
  })

  it('sends no date of death for a resignation', async () => {
    post.mockResolvedValue({ id: 'k1' })
    wrap(<CessationDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText(/Officer/), 'o2')
    await userEvent.click(screen.getByLabelText('Resignation / Others'))
    await userEvent.click(screen.getByRole('button', { name: 'Add cessation' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/entries', {
      kind: 'cessation', officer_id: 'o2', effective_date: '2026-09-20',
      cessation_reason: 'R', date_of_death: null }))
  })

  it('shows the date an entry already holds when it is edited', () => {
    const entry = { id: 'n1', kind: 'cessation', party_type: 'individual', officer_id: 'o1',
      capacity: 'director', cessation_reason: 'D', date_of_death: '2026-09-17',
      effective_date: '2026-09-17', party: { name: 'CHAN Tai Man' } }
    wrap(<CessationDrawer data={BASE} entry={entry} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByLabelText(/Date of death/)).toHaveValue('2026-09-17')
  })
})

describe('AppointmentDrawer — Get Started HK Limited first for a secretary', () => {
  const GSHK = { id: 'g1', company_name: 'Get Started HK Limited', br_number: '67169839' }
  const OTHER = { id: 'c2', company_name: 'Alpha Secretarial Limited', br_number: '12345678' }

  beforeEach(() => {
    get.mockImplementation(path => Promise.resolve(
      path.startsWith('/companies?search=67169839') ? { companies: [GSHK] }
        : path.startsWith('/companies?search=') ? { companies: [OTHER, GSHK] } : {}))
  })

  it('offers it before anything is typed, and picks it in one press', async () => {
    wrap(<AppointmentDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.click(screen.getByLabelText('Company Secretary'))
    await userEvent.click(screen.getByRole('button', { name: 'Body corporate' }))
    await userEvent.click(await screen.findByRole('option', { name: /Get Started HK Limited/ }))
    expect(screen.getByText('Get Started HK Limited', { selector: '.f-static' })).toBeInTheDocument()
  })

  it('lists it first among the search results', async () => {
    wrap(<AppointmentDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.click(screen.getByLabelText('Company Secretary'))
    await userEvent.click(screen.getByRole('button', { name: 'Body corporate' }))
    await userEvent.type(screen.getByLabelText(/Body corporate/, { selector: 'input' }), 'Limited')
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2))
    expect(screen.getAllByRole('option').map(o => o.textContent)[0]).toMatch(/Get Started HK Limited/)
  })

  it('asks the capacity before who is appointed', () => {
    wrap(<AppointmentDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    const capacity = screen.getByLabelText('Director')
    const search = screen.getByLabelText(/Person/, { selector: 'input' })
    expect(capacity.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('does not steer a director appointment to it', async () => {
    wrap(<AppointmentDrawer data={BASE} onClose={() => {}} onSaved={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Body corporate' }))
    expect(screen.queryByRole('option', { name: /Get Started HK Limited/ })).not.toBeInTheDocument()
    expect(get.mock.calls.some(([p]) => p.startsWith('/companies?search=67169839'))).toBe(false)
  })
})

describe('the e-Sign route\'s signed form, on the company', () => {
  const esign = { ...BASE, signing_method: 'esign', applied_at: 'x', profile_changes: [],
    documents: [], filing: { stage: 'submitted', submitted_at: '2026-10-17T07:05:00Z' },
    receipt: { caseNo: '141946253' } }

  it('says where it was saved', () => {
    wrap(<StageConfirmation data={{ ...esign, filed_form_document_id: 'DOC9',
      filed_form_document_version: 2 }} reload={vi.fn()} can={ALL} />)
    expect(screen.getByText(/Saved to the company's documents \(version 2\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save the signed form' })).not.toBeInTheDocument()
  })

  it('offers to save one that filing did not', async () => {
    post.mockResolvedValue({ ...esign, filed_form: { document_id: 'DOC9', version: 1 },
      write_back: { errors: [] } })
    const reload = vi.fn()
    wrap(<StageConfirmation data={esign} reload={reload} can={ALL} />)
    expect(screen.getByText(/The signed form was not saved to the company's documents/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save the signed form' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/apply', { confirm: true })
    await waitFor(() => expect(reload).toHaveBeenCalled())
  })

  it('says why, when saving it fails again', async () => {
    post.mockResolvedValue({ ...esign, filed_form: { error: 'storage down' },
      write_back: { errors: [] } })
    wrap(<StageConfirmation data={esign} reload={vi.fn()} can={ALL} />)
    await userEvent.click(screen.getByRole('button', { name: 'Save the signed form' }))
    expect(await screen.findByText('storage down')).toBeInTheDocument()
  })

  it('is not asked of the manual route, whose upload is the signed form', () => {
    wrap(<StageConfirmation data={{ ...BASE, signing_method: 'manual', applied_at: 'x',
      manual_receipt: { caseNo: '1' }, profile_changes: [], documents: [] }}
                            reload={vi.fn()} can={ALL} />)
    expect(screen.queryByText(/signed form was not saved/)).not.toBeInTheDocument()
  })

  it('reports a failed save as a warning on the filing', async () => {
    post.mockResolvedValue({ id: 'k1', write_back: { errors: [] }, documents_filed: [],
      filed_form: { error: 'storage down' } })
    const data = { ...BASE, signing_method: 'esign', filing: { stage: 'signed' },
      profile_changes: [], documents: [] }
    wrap(<StageSubmission data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    await userEvent.click(screen.getByLabelText(/Filing it with the Companies Registry cannot be undone/))
    await userEvent.click(screen.getByRole('button', { name: 'File ND2A with CR' }))
    await userEvent.click(screen.getByRole('button', { name: 'File with CR' }))
    expect(await screen.findByText(/storage down/)).toBeInTheDocument()
  })
})
