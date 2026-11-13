// Who signs an e-Signed ND2A: GSHK's e-Service, or a director's own e-Registry
// account (Levi 2026-11-13).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import SignerChoice from './SignerChoice.jsx'
import StageSigning from './StageSigning.jsx'
import StageDataVerification from './StageDataVerification.jsx'

const patch = vi.fn(); const post = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: {
    get: vi.fn(), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: vi.fn(), upload: vi.fn(), put: vi.fn(), blob: vi.fn(),
  },
}))

const BEN = { person_id: 'p2', name: 'Ben LAU', eservice_user_id: 'ER-BEN', ready: true,
  reason: null, profile_path: '/persons/p2' }
const ADA = { person_id: 'p1', name: 'Ada CHAN', eservice_user_id: null, ready: false,
  reason: 'e-Registry not set up', profile_path: '/persons/p1' }
const SIGNER = {
  offered: true, party: 'director', default: 'director', stored: false,
  changes_secretary: true, director_person_id: 'p2', director_ready: true,
  candidates: [BEN, ADA],
  gshk: { signs_for: 'Get Started HK Limited',
    capacity: 'Director of the Company Secretary (Body Corporate)', eservice_user_id: 'STAFF-1' },
}
const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('SignerChoice', () => {
  it('draws nothing when the form does not offer the choice', () => {
    const { container } = wrap(<SignerChoice signer={{ offered: false }} can={ALL} onChoose={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('suggests a director on a secretary change and says why', () => {
    wrap(<SignerChoice signer={SIGNER} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByText(/changes the company secretary/)).toBeInTheDocument()
    expect(screen.getByText('Suggested')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Director's e-Registry/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Ben LAU signs' })).toBeChecked()
  })

  it('names the account that signs on each option', () => {
    wrap(<SignerChoice signer={SIGNER} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByText('STAFF-1')).toBeInTheDocument()
    expect(screen.getByText('ER-BEN')).toBeInTheDocument()
  })

  it('toggles to GSHK with one click', async () => {
    const onChoose = vi.fn()
    wrap(<SignerChoice signer={SIGNER} can={ALL} onChoose={onChoose} />)
    await userEvent.click(screen.getByRole('radio', { name: /GSHK e-Service/ }))
    expect(onChoose).toHaveBeenCalledWith({ signing_party: 'gshk' })
  })

  it('toggles to a specific director', async () => {
    const onChoose = vi.fn()
    wrap(<SignerChoice signer={{ ...SIGNER, party: 'gshk', default: 'gshk', changes_secretary: false }}
                       can={ALL} onChoose={onChoose} />)
    expect(screen.getByRole('radio', { name: /GSHK e-Service/ })).toBeChecked()
    await userEvent.click(screen.getByRole('radio', { name: 'Ben LAU signs' }))
    expect(onChoose).toHaveBeenCalledWith({ signing_party: 'director', signing_director_person_id: 'p2' })
  })

  it('disables a director with no e-Registry and points at their profile', () => {
    wrap(<SignerChoice signer={SIGNER} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: 'Ada CHAN signs' })).toBeDisabled()
    const row = screen.getByText('Ada CHAN').closest('li')
    expect(within(row).getByText('e-Registry not set up')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'Set up on profile' })).toHaveAttribute('href', '/persons/p1')
  })

  it('disables the director option entirely when no director has e-Registry set up', () => {
    const signer = { ...SIGNER, party: 'gshk', default: 'gshk', director_person_id: null,
      director_ready: false, candidates: [ADA] }
    wrap(<SignerChoice signer={signer} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /Director's e-Registry/ })).toBeDisabled()
    expect(screen.getByText(/Director e-Registry is not set up/)).toBeInTheDocument()
    expect(screen.queryByText('Suggested')).not.toBeInTheDocument()
  })

  it('warns that changing the signer after validation means validating again', () => {
    wrap(<SignerChoice signer={SIGNER} can={ALL} validated onChoose={vi.fn()} />)
    expect(screen.getByText(/back to CR to validate again/)).toBeInTheDocument()
  })

  it('is read-only once the form is signed', () => {
    wrap(<SignerChoice signer={SIGNER} can={ALL} validated locked onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /GSHK e-Service/ })).toBeDisabled()
    expect(screen.getByText(/The form is signed/)).toBeInTheDocument()
  })

  it('greys out GSHK while the form only appoints it, and says why', () => {
    // DEV 2026-11-13: CR refused "The user has no association with this company".
    const signer = { ...SIGNER, gshk: { ...SIGNER.gshk, available: false,
      reason: 'Get Started HK Limited becomes the company secretary only when CR registers this form' } }
    wrap(<SignerChoice signer={signer} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /GSHK e-Service/ })).toBeDisabled()
    expect(screen.getByText(/is not yet the company secretary/)).toBeInTheDocument()
    expect(screen.getByText(/no association with this company/)).toBeInTheDocument()
    expect(screen.queryByText('STAFF-1')).not.toBeInTheDocument()
  })

  it('offers a director who resigns on this form, and says so', () => {
    const signer = { ...SIGNER, candidates: [{ ...BEN, ceasing: true }, ADA] }
    wrap(<SignerChoice signer={signer} can={ALL} onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: 'Ben LAU signs' })).toBeEnabled()
    expect(screen.getByText('resigning on this form')).toBeInTheDocument()
  })

  it('is read-only for a role that cannot write', () => {
    wrap(<SignerChoice signer={SIGNER} can={{ write: false }} onChoose={vi.fn()} />)
    expect(screen.getByRole('radio', { name: /GSHK e-Service/ })).toBeDisabled()
  })
})

describe('StageDataVerification — who signs is chosen before CR validates', () => {
  const DATA = {
    id: 'k1', case_no: 'ND2A-2026-0020', form_code: 'Nd2a', case_type: 'ND2A',
    client_approved: true, signing_method: 'esign', manual_checks: [], entries: [],
    dates_missing: [], route: { esign_available: true, default: 'esign', reasons: [] },
    signatory: { name: 'Ben LAU', party: 'director', default_capacity: 'Director' },
    signer: SIGNER, filing: null,
  }
  beforeEach(() => { patch.mockReset(); post.mockReset() })

  it('shows the chooser on e-Sign and drops the secretary capacity when a director signs', () => {
    wrap(<StageDataVerification data={DATA} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByTestId('signer-choice')).toBeInTheDocument()
    expect(screen.queryByLabelText(/signs as/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Validate with CR Portal' })).toBeEnabled()
  })

  it('switches to a director through PATCH', async () => {
    patch.mockResolvedValue({ id: 'k1' })
    const data = { ...DATA, signer: { ...SIGNER, party: 'gshk', default: 'gshk' },
      signatory: { name: 'Get Started HK Limited', party: 'gshk', capacities: ['Director'],
        default_capacity: 'Director' } }
    wrap(<StageDataVerification data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Ben LAU signs' }))
    expect(patch).toHaveBeenCalledWith('/officer-changes/k1',
      { signing_party: 'director', signing_director_person_id: 'p2' })
  })

  it('holds Validate while no director can sign and GSHK cannot either', () => {
    const data = { ...DATA, signer: { ...SIGNER, director_ready: false, candidates: [ADA],
      gshk: { ...SIGNER.gshk, available: false } } }
    wrap(<StageDataVerification data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Validate with CR Portal' })).toBeDisabled()
    expect(screen.getByText(/file by the Manual route/, { selector: '.f-hint' })).toBeInTheDocument()
  })

  it('keeps the chooser off the manual route', () => {
    const data = { ...DATA, signing_method: 'manual' }
    wrap(<StageDataVerification data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByTestId('signer-choice')).not.toBeInTheDocument()
  })
})

describe('StageSigning — who signs is chosen once, on Data Verification', () => {
  const DATA = {
    id: 'k1', case_no: 'ND2A-2026-0020', form_code: 'Nd2a', case_type: 'ND2A',
    client_approved: true, entries: [], dates_missing: [],
    route: { esign_available: true, reasons: [], consents: [] },
    signatory: { name: 'Ben LAU', party: 'director', default_capacity: 'Director' },
    signer: SIGNER, filing: null,
  }
  beforeEach(() => { patch.mockReset(); post.mockReset() })

  it('restates the chosen director, read-only, with the account that signs', () => {
    wrap(<StageSigning data={DATA} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    const summary = screen.getByTestId('signer-summary')
    expect(within(summary).getByText('Ben LAU')).toBeInTheDocument()
    expect(within(summary).getByText(/as Director/)).toBeInTheDocument()
    expect(within(summary).getByText('ER-BEN')).toBeInTheDocument()
    expect(screen.queryByTestId('signer-choice')).not.toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })

  it('restates GSHK with its capacity and e-Service account', () => {
    const data = { ...DATA, signer: { ...SIGNER, party: 'gshk', default: 'gshk' },
      signatory: { name: 'Get Started HK Limited', party: 'gshk',
        selected_capacity: 'Director of the Company Secretary (Body Corporate)' } }
    wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    const summary = screen.getByTestId('signer-summary')
    expect(within(summary).getByText('Get Started HK Limited')).toBeInTheDocument()
    expect(within(summary).getByText('GSHK e-Service')).toBeInTheDocument()
    expect(within(summary).getByText('STAFF-1')).toBeInTheDocument()
  })

  it('says when the director signing resigns on this form', () => {
    const data = { ...DATA, signer: { ...SIGNER, candidates: [{ ...BEN, ceasing: true }, ADA] } }
    wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByText('resigning on this form')).toBeInTheDocument()
  })

  it('sends the operator back to Data Verification to change it, without saving anything', async () => {
    const goTo = vi.fn()
    wrap(<StageSigning data={DATA} reload={vi.fn()} can={ALL} goTo={goTo} />)
    await userEvent.click(screen.getByRole('button', { name: 'Change on Data Verification' }))
    expect(goTo).toHaveBeenCalledWith(2)
    expect(patch).not.toHaveBeenCalled()
  })

  it('offers no change once the form is signed, or to a role that cannot write', () => {
    const signed = { ...DATA, filing: { stage: 'signed' } }
    const { unmount } = wrap(<StageSigning data={signed} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Change on Data Verification' })).not.toBeInTheDocument()
    unmount()
    wrap(<StageSigning data={DATA} reload={vi.fn()} can={{ ...ALL, write: false }} goTo={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Change on Data Verification' })).not.toBeInTheDocument()
  })

  it('holds Validate while the chosen director can no longer sign, and points back', () => {
    const data = { ...DATA, signer: { ...SIGNER, director_ready: false,
      candidates: [{ ...BEN, ready: false, reason: 'e-Registry password missing' }, ADA] } }
    wrap(<StageSigning data={data} reload={vi.fn()} can={ALL} goTo={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Validate with CR' })).toBeDisabled()
    expect(screen.getByText('Choose who signs on Data Verification first.')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/Ben LAU cannot sign yet: e-Registry password missing/)
  })
})
