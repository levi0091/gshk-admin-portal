import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import CrRefusal from './CrRefusal.jsx'

describe('CrRefusal', () => {
  it("prints CR's own words and, beside them, what the refusal means", () => {
    render(<CrRefusal error={{
      message: 'The Companies Registry rejected this form.',
      problems: [['ERROR', 'signer does not match with officer.']],
      hints: ["A new director's particulars on this form must match their e-Registry account exactly."],
    }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('rejected this form')
    expect(screen.getByText('ERROR: signer does not match with officer.')).toBeInTheDocument()
    expect(screen.getByText(/must match their e-Registry account exactly/)).toBeInTheDocument()
  })

  it('renders nothing without an error, and plain string problems as they are', () => {
    const { container, rerender } = render(<CrRefusal error={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<CrRefusal error={{ message: 'Refused', problems: ['brNo: too long'] }} />)
    expect(screen.getByText('brNo: too long')).toBeInTheDocument()
  })
})
