import { render, screen, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import PdfFrame from './PdfPreview.jsx'

// What `describeError` hands the pane for the 400 the stage-1 preview now
// returns when the builder refuses a value (PROD 2026-09-19, a Tab pasted into
// Payward Limited's BR number). Until then the pane printed "Failed to fetch".
const REFUSED = {
  message: 'The return cannot be built from the company record: the Companies '
    + 'Registry would refuse these values. Correct them on the company profile, '
    + 'then try again.',
  problems: [
    'Business Registration number: contains a Tab or another invisible control '
      + 'character, which CR refuses — retype the value rather than pasting it',
    'Company name (English): contains a Tab',
  ],
  hint: null,
}

describe('PdfFrame — why there is no preview', () => {
  it('lists every field the backend named, not only the summary sentence', () => {
    render(<PdfFrame error={REFUSED} label="NAR1 preview" />)
    const items = within(screen.getByRole('list')).getAllByRole('listitem')
    expect(items.map(li => li.textContent)).toEqual(REFUSED.problems)
  })

  it('still says what went wrong above the list', () => {
    render(<PdfFrame error={REFUSED} label="NAR1 preview" />)
    expect(screen.getByText('The preview could not be rendered.')).toBeInTheDocument()
    expect(screen.getByText(/Correct them on the company profile/)).toBeInTheDocument()
  })

  it('draws no empty list when the failure carried no problems', () => {
    render(<PdfFrame error={{ message: 'Could not reach the server.', hint: null }}
                     label="NAR1 preview" />)
    expect(screen.getByText('Could not reach the server.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })

  it('keeps the hint for a failure that has one', () => {
    render(<PdfFrame error={{ message: 'Nope.', hint: 'Try again later.' }}
                     label="NAR1 preview" />)
    expect(screen.getByText('Try again later.')).toBeInTheDocument()
  })
})
