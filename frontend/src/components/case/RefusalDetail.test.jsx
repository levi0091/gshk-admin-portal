import { render, screen, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import RefusalDetail from './RefusalDetail.jsx'

const DIFF = {
  path: 'indDirList/indDir[2]/stdAddress/stEstLotVlg',
  field: 'Director (individual) 2 · Address · Street / estate / lot / village',
  validated: 'Raggatan 9, Stockholm 11859',
  current: 'Raggatan 14, Stockholm 11859',
}

describe('RefusalDetail — a filed particular that moved', () => {
  it('shows BOTH values, so the operator can tell which record is right', () => {
    render(<RefusalDetail differences={[DIFF]} />)
    const card = screen.getByTestId('mismatch-card')
    expect(within(card).getByText('Raggatan 9, Stockholm 11859')).toBeInTheDocument()
    expect(within(card).getByText('Raggatan 14, Stockholm 11859')).toBeInTheDocument()
  })

  it('says which is which, in the operator\'s terms not the wire format\'s', () => {
    render(<RefusalDetail differences={[DIFF]} />)
    const card = screen.getByTestId('mismatch-card')
    expect(within(card).getByText(/On the NAR1 the client approved/)).toBeInTheDocument()
    expect(within(card).getByText(/In the company profile now/)).toBeInTheDocument()
  })

  it('separates the route through the form from the field at the end of it', () => {
    render(<RefusalDetail differences={[DIFF]} />)
    const card = screen.getByTestId('mismatch-card')
    // The field is the subject and carries the weight; the route is context.
    expect(within(card).getByText('Street / estate / lot / village'))
      .toHaveClass('rf-where-field')
    expect(within(card).getByText('Director (individual) 2'))
      .toHaveClass('rf-where-step')
  })

  it('renders an ABSENT value as words, never as an empty pane', () => {
    // A director who left the board has no field at all. A blank would read as
    // "unchanged, empty" — which is a different fact entirely.
    render(<RefusalDetail differences={[{ ...DIFF, current: null }]} />)
    expect(screen.getByText('No longer on record')).toBeInTheDocument()
  })

  it('renders a value that is newly present as absent on the form side', () => {
    render(<RefusalDetail differences={[{ ...DIFF, validated: null }]} />)
    expect(screen.getByText('Not on the form')).toBeInTheDocument()
  })

  it('draws one card per field, not one paragraph for all of them', () => {
    render(<RefusalDetail differences={[DIFF, { ...DIFF, path: 'brNo', field: 'BR number' }]} />)
    expect(screen.getAllByTestId('mismatch-card')).toHaveLength(2)
  })
})

describe('RefusalDetail — a record that cannot make a return', () => {
  // Verbatim from the screen Levi photographed on 2026-09-03.
  const PROBLEM =
    "corporate party CGAHCHBAABBG DIRECTOR COMPANY LIMITED: no CR region code "
    + "is known for country 'HK-CH' — CR's Country & Region sheet (worksheet "
    + "v1.0.14) carries no code, alpha-2 or English name matching it; correct "
    + "the address rather than guessing a code CR would take the fee for and "
    + "then reject"

  it('names the party, the fault and the explanation as three things', () => {
    render(<RefusalDetail problems={[PROBLEM]} />)
    const card = screen.getByTestId('problem-card')
    expect(within(card).getByText('CGAHCHBAABBG DIRECTOR COMPANY LIMITED'))
      .toHaveClass('rf-where-field')
    expect(within(card).getByText('Corporate party')).toBeInTheDocument()
    expect(within(card).getByText(/^No CR region code is known/)).toHaveClass('rf-problem')
    expect(within(card).getByText(/Country & Region sheet/)).toHaveClass('rf-detail')
  })

  it('loses nothing from the original fault text', () => {
    render(<RefusalDetail problems={[PROBLEM]} />)
    const card = screen.getByTestId('problem-card')
    expect(card.textContent).toMatch(/HK-CH/)
    expect(card.textContent).toMatch(/worksheet v1\.0\.14/)
    expect(card.textContent).toMatch(/then reject/)
  })

  it('draws one card per fault', () => {
    render(<RefusalDetail problems={[PROBLEM, 'entity: no BR number']} />)
    expect(screen.getAllByTestId('problem-card')).toHaveLength(2)
  })

  it('renders CR\'s [severity, message] pair without printing the severity', () => {
    // CR's wire shape. "ERROR" above a card that is already inside a refusal
    // is not a place on the record and reads like one.
    render(<RefusalDetail problems={[['ERROR', 'Please check selectPersonId field.']]} />)
    const card = screen.getByTestId('problem-card')
    expect(card.textContent).toMatch(/Please check selectPersonId field/)
    expect(card.textContent).not.toMatch(/ERROR/)
  })

  it('renders a fault that matches no shape at all, rather than dropping it', () => {
    render(<RefusalDetail problems={['something is wrong']} />)
    expect(screen.getByText('Something is wrong.')).toBeInTheDocument()
  })
})

describe('RefusalDetail — nothing to show', () => {
  it('renders nothing at all when there is no evidence', () => {
    const { container } = render(<RefusalDetail />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing for empty lists', () => {
    const { container } = render(<RefusalDetail differences={[]} problems={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
