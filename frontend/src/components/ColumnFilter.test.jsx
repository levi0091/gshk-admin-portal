import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FilterableTh from './FilterableTh.jsx'
import { ENUM, RANGE, TEXT } from '../lib/tableFilters.js'

const NAME = { col: 'company_name', label: 'Company Name', sort: 'company_name',
               filter: { kind: TEXT } }
const STATUS = {
  col: 'status', label: 'Status', sort: 'status',
  filter: { kind: ENUM, options: [
    { value: 'live', label: 'Live', count: 12 },
    { value: 'ceased', label: 'Ceased', count: 3 },
  ] },
}
const DAYS = {
  col: 'days_to_anniversary', label: 'Days to anniversary', sort: 'days_to_anniversary',
  filter: { kind: RANGE, unit: 'days', hint: 'A passed anniversary counts negative.' },
}

function setup(column, filters = []) {
  const onFilter = vi.fn()
  const onSort = vi.fn()
  render(
    <table><thead><tr>
      <FilterableTh column={column} sort={null} dir="asc" onSort={onSort}
                    filters={filters} onFilter={onFilter} />
    </tr></thead></table>,
  )
  return { onFilter, onSort, user: userEvent.setup() }
}

const funnel = (label = 'Company Name') =>
  screen.getByRole('button', { name: new RegExp(`^Filter ${label}`) })

describe('the funnel', () => {
  it('opens a dialog for the column it sits in', async () => {
    const { user } = setup(NAME)
    await user.click(funnel())
    expect(screen.getByRole('dialog', { name: 'Filter Company Name' })).toBeInTheDocument()
  })

  it('does NOT sort the table when clicked', async () => {
    // The header itself is the sort target. Filtering through it must not
    // reorder the table as a side effect of asking to narrow it.
    const { user, onSort } = setup(NAME)
    await user.click(funnel())
    expect(onSort).not.toHaveBeenCalled()
  })

  it('says it is filtering when this column has a filter applied', async () => {
    setup(NAME, [{ col: 'company_name', op: 'contains', value: 'acme' }])
    expect(screen.getByRole('button', { name: 'Filter Company Name (filtered)' }))
      .toHaveClass('is-on')
  })

  it('marks the whole header, not only the icon', () => {
    // A 11px icon three columns off-screen is not a state indicator.
    const { container } = render(
      <table><thead><tr>
        <FilterableTh column={NAME} sort={null} dir="asc" onSort={() => {}}
                      filters={[{ col: 'company_name', op: 'contains', value: 'a' }]}
                      onFilter={() => {}} />
      </tr></thead></table>,
    )
    expect(container.querySelector('th')).toHaveClass('th-filtered')
  })

  it('reads as unfiltered when another column is the one narrowing', () => {
    setup(NAME, [{ col: 'status', op: 'in', value: ['live'] }])
    expect(funnel()).not.toHaveClass('is-on')
  })
})

describe('committing a filter', () => {
  it('applies nothing until Apply is pressed', async () => {
    const { user, onFilter } = setup(NAME)
    await user.click(funnel())
    await user.type(screen.getByLabelText('Company Name value'), 'acme')
    expect(onFilter).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(NAME,
      [{ col: 'company_name', op: 'contains', value: 'acme' }])
  })

  it('discards the draft when Escape closes the panel', async () => {
    const { user, onFilter } = setup(NAME)
    await user.click(funnel())
    await user.type(screen.getByLabelText('Company Name value'), 'acme')
    await user.keyboard('{Escape}')
    expect(onFilter).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('discards the draft when a click lands outside', async () => {
    const { user, onFilter } = setup(NAME)
    await user.click(funnel())
    await user.type(screen.getByLabelText('Company Name value'), 'acme')
    await user.click(document.body)
    expect(onFilter).not.toHaveBeenCalled()
  })

  it('Clear commits at once, because dropping a filter is unambiguous', async () => {
    const { user, onFilter } = setup(NAME,
      [{ col: 'company_name', op: 'contains', value: 'acme' }])
    await user.click(screen.getByRole('button', { name: /^Filter Company Name/ }))
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(onFilter).toHaveBeenCalledWith(NAME, [])
  })

  it('opens showing the filter already applied, not a blank form', async () => {
    const { user } = setup(NAME, [{ col: 'company_name', op: 'eq', value: 'ACME LTD' }])
    await user.click(screen.getByRole('button', { name: /^Filter Company Name/ }))
    expect(screen.getByLabelText('Company Name value')).toHaveValue('ACME LTD')
    expect(screen.getByLabelText('Condition')).toHaveValue('eq')
  })

  it('hides the value box for a condition that takes no value', async () => {
    const { user, onFilter } = setup(NAME)
    await user.click(funnel())
    await user.selectOptions(screen.getByLabelText('Condition'), 'empty')
    expect(screen.queryByLabelText('Company Name value')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(NAME,
      [{ col: 'company_name', op: 'empty', value: '' }])
  })
})

describe('the checkbox list', () => {
  it('carries the counts the removed tab row used to show', async () => {
    const { user } = setup(STATUS)
    await user.click(funnel('Status'))
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('picks several values at once', async () => {
    const { user, onFilter } = setup(STATUS)
    await user.click(funnel('Status'))
    await user.click(screen.getByRole('checkbox', { name: /Live/ }))
    await user.click(screen.getByRole('checkbox', { name: /Ceased/ }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(STATUS,
      [{ col: 'status', op: 'in', value: ['live', 'ceased'] }])
  })

  it('offers radios where the API can only answer one value', async () => {
    // A checkbox that silently unticks its neighbour is a control lying about
    // what it does.
    const single = { ...STATUS, filter: { ...STATUS.filter, single: true } }
    const { user, onFilter } = setup(single)
    await user.click(funnel('Status'))
    await user.click(screen.getByRole('radio', { name: /Live/ }))
    await user.click(screen.getByRole('radio', { name: /Ceased/ }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(single,
      [{ col: 'status', op: 'in', value: ['ceased'] }])
  })
})

// The panel is PORTALLED to document.body: the header lives inside
// `.tbl-wrap`, which is `overflow-x: auto` so wide tables scroll, and an
// absolutely-positioned panel would be clipped by exactly the scroller that
// makes the far-right columns reachable. Portalling means the position has to
// be computed rather than inherited, and jsdom hands back zeros for every
// rectangle — so these stub the geometry to exercise the arithmetic.
describe('where the panel lands', () => {
  function place({ top, bottom, left, panelH = 200, panelW = 248,
                   viewH = 900, viewW = 1280 }) {
    window.innerHeight = viewH
    window.innerWidth = viewW
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ top, bottom, left, right: left + 18, width: 18, height: 18 })
    const h = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(panelH)
    const w = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(panelW)
    return () => { rect.mockRestore(); h.mockRestore(); w.mockRestore() }
  }

  it('sits just under the funnel that opened it', async () => {
    const restore = place({ top: 100, bottom: 120, left: 300 })
    const { user } = setup(NAME)
    await user.click(funnel())
    const panel = screen.getByRole('dialog')
    expect(panel).toHaveStyle({ position: 'fixed', top: '126px', left: '300px' })
    restore()
  })

  it('flips above the header when there is no room below', async () => {
    // Otherwise the last columns of a long page open a panel off the bottom of
    // the screen, and the Apply button is unreachable.
    const restore = place({ top: 780, bottom: 800, left: 300 })
    const { user } = setup(NAME)
    await user.click(funnel())
    expect(screen.getByRole('dialog')).toHaveStyle({ top: '574px' })
    restore()
  })

  it('pulls back from the right edge rather than overflowing it', async () => {
    const restore = place({ top: 100, bottom: 120, left: 1200 })
    const { user } = setup(NAME)
    await user.click(funnel())
    expect(screen.getByRole('dialog')).toHaveStyle({ left: '1024px' })
    restore()
  })
})

describe('the range panel', () => {
  it('takes an upper and a lower bound', async () => {
    const { user, onFilter } = setup(DAYS)
    await user.click(funnel('Days to anniversary'))
    await user.type(screen.getByLabelText('Days to anniversary lower bound'), '-42')
    await user.type(screen.getByLabelText('Days to anniversary upper bound'), '60')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(DAYS, [
      { col: 'days_to_anniversary', op: 'gte', value: -42 },
      { col: 'days_to_anniversary', op: 'lte', value: 60 },
    ])
  })

  it('explains why the numbers go negative', async () => {
    const { user } = setup(DAYS)
    await user.click(funnel('Days to anniversary'))
    expect(screen.getByText(/passed anniversary counts negative/)).toBeInTheDocument()
  })

  it('accepts one bound on its own', async () => {
    const { user, onFilter } = setup(DAYS)
    await user.click(funnel('Days to anniversary'))
    await user.type(screen.getByLabelText('Days to anniversary upper bound'), '0')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onFilter).toHaveBeenCalledWith(DAYS,
      [{ col: 'days_to_anniversary', op: 'lte', value: 0 }])
  })
})
