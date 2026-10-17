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
  // The six CR codes that replaced it are gone too (Levi 2026-10-17): CR will
  // not report a status after filing, so a filed return reads Filed.
  'filed',
  'closed',
]
const FORM_CODES = [
  'draft', 'validated', 'validation_failed', 'signed', 'signing_failed',
  'submitted', 'submission_failed', 'superseded', 'edrive',
]

describe('WorkflowBadge', () => {
  it('labels every one of the eight workflow statuses', () => {
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

  it('does not dress a closed case in the colour of a filed one', () => {
    // Both are finished; only one was filed. Reading them as the same thing at
    // a glance is the one mistake this badge must not invite (Levi 2026-09-05).
    expect(WORKFLOW_CLASS.closed).not.toBe(WORKFLOW_CLASS.filed)
    expect(WORKFLOW_LABEL.closed).toBe('Closed')
    expect(WORKFLOW_LABEL.filed).toBe('Filed')
  })

  it('has no `completed` left to send', () => {
    // Removed, not aliased. A code no row can carry but that every filter,
    // count and test still offers renders an always-zero tab on the dashboard
    // and invites the next writer to set it.
    expect(WORKFLOW_LABEL.completed).toBeUndefined()
    expect(WORKFLOW_CLASS.completed).toBeUndefined()
  })

  it('renders a bare filed code as Filed', () => {
    render(<WorkflowBadge status="filed" />)
    expect(screen.getByText('Filed')).toBeInTheDocument()
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
      code: 'filed', label: 'Filed', off_portal: true, overdue: false,
    }} />)
    expect(screen.getByText('Filed')).toBeInTheDocument()
    expect(screen.getByText('Off-portal')).toBeInTheDocument()
  })

  it('does not render an off-portal marker for a normal case', () => {
    render(<WorkflowBadge status={{
      code: 'filed', label: 'Filed', off_portal: false, overdue: false,
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
    // Two families again: the third, `bc-*` (what CR's register said), went
    // with the CR status stage on 2026-10-17.
    expect(Object.values(WORKFLOW_CLASS).every(c => c.startsWith('bw-'))).toBe(true)
    expect(Object.values(FORM_CLASS).every(c => c.startsWith('bf-'))).toBe(true)
  })
})
