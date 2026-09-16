import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import {
  WorkflowBadge, FormBadge,
  WORKFLOW_LABEL, WORKFLOW_CLASS, FORM_LABEL, FORM_CLASS,
} from './CaseStatusBadge.jsx'

// The backend's vocabularies. If either list grows, these arrays are what fails
// first — a code with no label renders as its raw snake_case at a user.
const WORKFLOW_CODES = [
  'data_verification', 'client_verification', 'awaiting_client',
  'client_rejected', 'signing', 'submission',
  // `completed` is GONE (Levi 2026-09-16). It was a word of ours standing in
  // for a decision only CR makes — a case went green the instant
  // submitFormNar1 returned a receipt, while CR had only RECEIVED the return.
  'cr_not_checked', 'cr_pending', 'cr_approved', 'cr_registered',
  'cr_rejected', 'cr_unknown',
  'closed',
]
const FORM_CODES = [
  'draft', 'validated', 'validation_failed', 'signed', 'signing_failed',
  'submitted', 'submission_failed', 'registered', 'superseded', 'edrive',
]

describe('WorkflowBadge', () => {
  it('labels every one of the thirteen workflow statuses', () => {
    for (const code of WORKFLOW_CODES) {
      expect(WORKFLOW_LABEL[code], `no label for ${code}`).toBeTruthy()
      expect(WORKFLOW_CLASS[code], `no class for ${code}`).toBeTruthy()
    }
    // And nothing extra: a map entry with no code behind it is a status the
    // backend cannot send, which means the maps and
    // `nar1_case_status.WORKFLOW_STATUSES` have drifted.
    expect(Object.keys(WORKFLOW_LABEL).sort()).toEqual([...WORKFLOW_CODES].sort())
    expect(Object.keys(WORKFLOW_CLASS).sort()).toEqual([...WORKFLOW_CODES].sort())
  })

  it('does not dress a closed case in the colour of a registered one', () => {
    // Both are finished; only one is on the register. Reading them as the same
    // thing at a glance is the one mistake this badge must not invite (Levi
    // 2026-09-05).
    expect(WORKFLOW_CLASS.closed).not.toBe(WORKFLOW_CLASS.cr_registered)
    expect(WORKFLOW_LABEL.closed).toBe('Closed')
  })

  it('has no `completed` left to send', () => {
    // Removed, not aliased. A code no row can carry but that every filter,
    // count and test still offers renders an always-zero tab on the dashboard
    // and invites the next writer to set it.
    expect(WORKFLOW_LABEL.completed).toBeUndefined()
    expect(WORKFLOW_CLASS.completed).toBeUndefined()
  })

  it('gives every CR answer its own colour, except the two greys', () => {
    // Five treatments over six codes. `cr_unknown` shares grey with
    // `cr_not_checked` because neither tells you anything actionable — and the
    // badge itself carries CR's own words to tell them apart.
    const cr = ['cr_not_checked', 'cr_pending', 'cr_approved', 'cr_registered',
                'cr_rejected', 'cr_unknown']
    expect(new Set(cr.map(c => WORKFLOW_CLASS[c])).size).toBe(6)
    expect(WORKFLOW_CLASS.cr_pending).not.toBe(WORKFLOW_CLASS.cr_registered)
    expect(WORKFLOW_CLASS.cr_rejected).not.toBe(WORKFLOW_CLASS.cr_registered)
  })

  it('shows CR\'s own words when the label alone says nothing', () => {
    // "Other CR status" is true and useless; what CR actually said is the only
    // informative thing there is.
    render(<WorkflowBadge status={{
      code: 'cr_unknown', label: 'Other CR status', cr_text: 'Vetting/2',
    }} />)
    expect(screen.getByText('Vetting/2')).toBeInTheDocument()
  })

  it('keeps CR\'s words in the title on a status it DOES recognise', () => {
    // The Workflow column is scanned. CR's wording matters when you stop on one
    // row, not on every row at once.
    render(<WorkflowBadge status={{
      code: 'cr_registered', label: 'Registered by CR', cr_text: 'Registered',
    }} />)
    const badge = screen.getByText('Registered by CR')
    expect(badge).toHaveAttribute('title', expect.stringContaining('Registered'))
  })

  it('renders a bare code with no CR words at all', () => {
    render(<WorkflowBadge status="cr_pending" />)
    expect(screen.getByText('Pending at CR')).toBeInTheDocument()
  })

  it('renders the label, not the raw code', () => {
    render(<WorkflowBadge status="data_verification" />)
    expect(screen.getByText('Data Verification')).toBeInTheDocument()
    expect(screen.queryByText('data_verification')).not.toBeInTheDocument()
  })

  // ---- the shape the backend ACTUALLY sends -------------------------------
  // badge_from_row()/derive() return a composite object, not a code. Rendering
  // it directly is React error #31 ("Objects are not valid as a React child"),
  // which unmounts the entire tree — the admin-dev blank dashboard. Every test
  // here used a bare string, so 318 of them passed while DEV was broken.

  it('accepts the composite badge object the backend sends', () => {
    render(<WorkflowBadge status={{
      code: 'signing', label: 'Signing', off_portal: false, overdue: false,
    }} />)
    expect(screen.getByText('Signing')).toBeInTheDocument()
  })

  it('colours the composite badge by its code', () => {
    const { container } = render(<WorkflowBadge status={{
      code: 'client_rejected', label: 'Client Rejected', off_portal: false, overdue: false,
    }} />)
    expect(container.querySelector('.badge.bw-rejected')).toBeTruthy()
  })

  it('prefers the label the SERVER derived over the local map', () => {
    // The backend derives the badge from two records and is the authority on
    // what it says; the local map is for a bare code and as a fallback.
    render(<WorkflowBadge status={{
      code: 'signing', label: 'Awaiting counter-signature', off_portal: false, overdue: false,
    }} />)
    expect(screen.getByText('Awaiting counter-signature')).toBeInTheDocument()
    expect(screen.queryByText('Signing')).not.toBeInTheDocument()
  })

  it('marks an off-portal filing beside the badge', () => {
    // e-Drive: finished at CR, but not by us. v11 has no badge for it.
    render(<WorkflowBadge status={{
      code: 'cr_registered', label: 'Registered by CR', off_portal: true, overdue: false,
    }} />)
    expect(screen.getByText('Registered by CR')).toBeInTheDocument()
    expect(screen.getByText('Off-portal')).toBeInTheDocument()
  })

  it('does not render an off-portal marker for a normal case', () => {
    render(<WorkflowBadge status={{
      code: 'cr_registered', label: 'Registered by CR', off_portal: false, overdue: false,
    }} />)
    expect(screen.queryByText('Off-portal')).not.toBeInTheDocument()
  })

  it('reads as an em dash for a badge object with no code', () => {
    render(<WorkflowBadge status={{ label: null, off_portal: false }} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('carries the bw-* class so the colour matches the filter tabs', () => {
    const { container } = render(<WorkflowBadge status="client_rejected" />)
    expect(container.querySelector('.badge.bw-rejected')).toBeTruthy()
  })

  it('reads as an em dash when there is no status', () => {
    render(<WorkflowBadge status={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('FormBadge', () => {
  it('labels every one of the CR form stages', () => {
    for (const code of FORM_CODES) {
      expect(FORM_LABEL[code], `no label for ${code}`).toBeTruthy()
      expect(FORM_CLASS[code], `no class for ${code}`).toBeTruthy()
    }
  })

  it('renders CR wording a filing clerk would recognise', () => {
    render(<FormBadge stage="submitted" />)
    expect(screen.getByText('Filed with CR')).toBeInTheDocument()
  })

  it('gives all three failure stages the same red, and says which step failed', () => {
    for (const stage of ['validation_failed', 'signing_failed', 'submission_failed']) {
      expect(FORM_CLASS[stage]).toBe('bf-failed')
    }
    // The label is what distinguishes them — the colour only says "CR refused".
    expect(FORM_LABEL.validation_failed).toContain('validation')
    expect(FORM_LABEL.signing_failed).toContain('signing')
    expect(FORM_LABEL.submission_failed).toContain('submission')
  })

  it('reads as an em dash when no filing exists yet', () => {
    // A case exists before anything is sent to CR. That is a normal state, not
    // a draft filing and not an error.
    render(<FormBadge stage={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('the two vocabularies stay apart', () => {
  it('shares no class between the workflow and form families', () => {
    // D-6. If a class ever appears in both maps, the two status questions have
    // started to look alike on screen — which is the confusion the split exists
    // to prevent.
    const workflow = new Set(Object.values(WORKFLOW_CLASS))
    const form = new Set(Object.values(FORM_CLASS))
    const shared = [...workflow].filter(c => form.has(c))
    expect(shared).toEqual([])
  })

  it('prefixes each family distinctly', () => {
    // THREE families now. `bc-*` is what CR's own register says about a
    // document it has already received — a third question, not a variant of
    // the other two, and the workflow badge is where it surfaces on a listing.
    // Sharing a prefix would let a reviewer take "where the case is" and "what
    // CR decided" for one vocabulary.
    expect(Object.values(WORKFLOW_CLASS)
      .every(c => c.startsWith('bw-') || c.startsWith('bc-'))).toBe(true)
    expect(Object.values(FORM_CLASS).every(c => c.startsWith('bf-'))).toBe(true)
    // And every CR code uses `bc-`, so the families cannot quietly mix.
    for (const code of Object.keys(WORKFLOW_CLASS)) {
      const expected = code.startsWith('cr_') ? 'bc-' : 'bw-'
      expect(WORKFLOW_CLASS[code].startsWith(expected), code).toBe(true)
    }
  })
})
