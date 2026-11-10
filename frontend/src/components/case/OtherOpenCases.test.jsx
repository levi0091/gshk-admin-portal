import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'

import OtherOpenCases from './OtherOpenCases.jsx'

const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('OtherOpenCases (Jacqueline AQ3, BQ1)', () => {
  it('names each other open case with a link, before anything goes to CR', () => {
    wrap(<OtherOpenCases cases={[
      { id: 'k2', case_no: 'ND2B-2026-0003', case_type: 'ND2B', form_code: 'Nd2b',
        workflow_status: { label: 'Awaiting client' } },
      { id: 'c9', case_no: 'NAR-2026-0042', case_type: 'NAR1', form_code: 'Nar1',
        workflow_status: { label: 'Data verification' } }]} />)
    expect(screen.getByRole('status')).toHaveTextContent(/This company has other filings open/)
    expect(screen.getByRole('link', { name: /ND2B-2026-0003/ })).toHaveAttribute('href', '/officer-changes/k2')
    expect(screen.getByRole('link', { name: /NAR-2026-0042/ })).toHaveAttribute('href', '/cases/c9')
    expect(screen.getByText(/Awaiting client/)).toBeInTheDocument()
  })

  it('renders nothing when there is none', () => {
    const { container } = wrap(<OtherOpenCases cases={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
