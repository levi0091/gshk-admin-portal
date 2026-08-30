import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import FaultPanel, { readFault } from './FaultPanel.jsx'

describe('readFault — every shape a fault actually arrives in', () => {
  it("reads CR's real [severity, message] pair", () => {
    // Captured live on 2026-08-27 from a rejected validateFormNar1:
    //   cr_error.faults = [["ERROR", "Please check selectPersonId field."]]
    // This was rendering as raw JSON at the operator.
    expect(readFault(['ERROR', 'Please check selectPersonId field.']))
      .toEqual({ field: 'ERROR', msg: 'Please check selectPersonId field.' })
  })

  it("reads the mapper's plain-string problems", () => {
    const p = 'signatory: no current company secretary on record'
    expect(readFault(p)).toEqual({ field: null, msg: p })
  })

  it('reads the documented {faultString, fieldName} object', () => {
    expect(readFault({ fieldName: 'indvHkidNo', faultString: 'Partial HKID required' }))
      .toEqual({ field: 'indvHkidNo', msg: 'Partial HKID required' })
  })

  it('never renders raw JSON for a one-element pair', () => {
    expect(readFault(['something went wrong']))
      .toEqual({ field: null, msg: 'something went wrong' })
  })
})

describe('FaultPanel', () => {
  it("renders CR's real pair shape as readable text, not JSON", () => {
    render(<FaultPanel faults={[['ERROR', 'Please check selectPersonId field.']]} />)
    expect(screen.getByText('Please check selectPersonId field.')).toBeInTheDocument()
    expect(screen.getByText('ERROR')).toBeInTheDocument()
    expect(screen.queryByText(/^\[/)).not.toBeInTheDocument()
  })

  it('renders EVERY fault and counts them', () => {
    render(<FaultPanel faults={[
      ['ERROR', 'Please check selectPersonId field.'],
      ['ERROR', 'signatoryDate precedes the appointment date.'],
    ]} />)
    expect(screen.getByText('Please check selectPersonId field.')).toBeInTheDocument()
    expect(screen.getByText('signatoryDate precedes the appointment date.')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders nothing at all when there is nothing wrong', () => {
    const { container } = render(<FaultPanel faults={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('takes a custom title, so our problems and CR faults read differently', () => {
    render(<FaultPanel faults={['x']} title="This company cannot be filed as a NAR1 yet" />)
    expect(screen.getByText('This company cannot be filed as a NAR1 yet')).toBeInTheDocument()
  })
})
