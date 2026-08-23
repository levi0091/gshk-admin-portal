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
  'client_rejected', 'signing', 'submission', 'completed',
]
const FORM_CODES = [
  'draft', 'validated', 'validation_failed', 'signed', 'signing_failed',
  'submitted', 'submission_failed', 'registered', 'superseded', 'edrive',
]

describe('WorkflowBadge', () => {
  it('labels every one of the seven workflow statuses', () => {
    for (const code of WORKFLOW_CODES) {
      expect(WORKFLOW_LABEL[code], `no label for ${code}`).toBeTruthy()
      expect(WORKFLOW_CLASS[code], `no class for ${code}`).toBeTruthy()
    }
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
      code: 'completed', label: 'Completed', off_portal: true, overdue: false,
    }} />)
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Off-portal')).toBeInTheDocument()
  })

  it('does not render an off-portal marker for a normal case', () => {
    render(<WorkflowBadge status={{
      code: 'completed', label: 'Completed', off_portal: false, overdue: false,
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
  it('shares no class between the bw-* and bf-* families', () => {
    // D-6. If a class ever appears in both maps, the two status questions have
    // started to look alike on screen — which is the confusion the split exists
    // to prevent.
    const workflow = new Set(Object.values(WORKFLOW_CLASS))
    const form = new Set(Object.values(FORM_CLASS))
    const shared = [...workflow].filter(c => form.has(c))
    expect(shared).toEqual([])
  })

  it('prefixes each family distinctly', () => {
    expect(Object.values(WORKFLOW_CLASS).every(c => c.startsWith('bw-'))).toBe(true)
    expect(Object.values(FORM_CLASS).every(c => c.startsWith('bf-'))).toBe(true)
  })
})
