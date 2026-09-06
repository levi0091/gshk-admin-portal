import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FilterChips from './FilterChips.jsx'
import { OWNER, RANGE, TEXT } from '../lib/tableFilters.js'

const COLUMNS = [
  { col: 'company_name', label: 'Company Name', filter: { kind: TEXT } },
  { col: 'days_to_anniversary', label: 'Days to anniversary',
    filter: { kind: RANGE, unit: 'days' } },
  { col: 'created_by', label: 'Created By',
    filter: { kind: OWNER, meId: 'u-1', nameCol: 'created_by_name' } },
]

function setup(filters, extra = []) {
  const onRemove = vi.fn()
  const onClearAll = vi.fn()
  render(<FilterChips columns={COLUMNS} filters={filters} extra={extra}
                      onRemove={onRemove} onClearAll={onClearAll} />)
  return { onRemove, onClearAll, user: userEvent.setup() }
}

it('draws nothing at all when the table is unfiltered', () => {
  const { container } = render(
    <FilterChips columns={COLUMNS} filters={[]} onRemove={() => {}} onClearAll={() => {}} />)
  expect(container).toBeEmptyDOMElement()
})

it('names the filter the dashboard applies before anyone touches it', () => {
  // The whole point. A default that hides rows and says nothing about it is
  // indistinguishable from a table that is simply missing data.
  setup([{ col: 'created_by', op: 'eq', value: 'u-1' }])
  expect(screen.getByText('Created By')).toBeInTheDocument()
  expect(screen.getByText('Me')).toBeInTheDocument()
})

it('drops a filter through its own chip', async () => {
  const { user, onRemove } = setup([{ col: 'company_name', op: 'contains', value: 'acme' }])
  await user.click(screen.getByRole('button', { name: /Remove the Company Name filter/ }))
  expect(onRemove).toHaveBeenCalledWith(['company_name'])
})

it('drops both columns behind an owner chip', async () => {
  // The uuid and the display name are one control; clearing half of it would
  // leave a filter applied with no funnel lit anywhere.
  const { user, onRemove } = setup([
    { col: 'created_by_name', op: 'contains', value: 'Levi' },
  ])
  await user.click(screen.getByRole('button', { name: /Remove the Created By filter/ }))
  expect(onRemove).toHaveBeenCalledWith(['created_by', 'created_by_name'])
})

it('collapses a two-ended range into one chip', () => {
  setup([
    { col: 'days_to_anniversary', op: 'gte', value: -42 },
    { col: 'days_to_anniversary', op: 'lte', value: 60 },
  ])
  expect(screen.getAllByRole('button', { name: /Remove the Days to anniversary/ }))
    .toHaveLength(1)
  expect(screen.getByText('-42 to 60 days')).toBeInTheDocument()
})

it('offers Clear all only once there is more than one thing to clear', async () => {
  const one = render(
    <FilterChips columns={COLUMNS} filters={[{ col: 'company_name', op: 'eq', value: 'a' }]}
                 onRemove={() => {}} onClearAll={() => {}} />)
  expect(screen.queryByRole('button', { name: 'Clear all' })).not.toBeInTheDocument()
  one.unmount()

  const { user, onClearAll } = setup([
    { col: 'company_name', op: 'eq', value: 'a' },
    { col: 'created_by', op: 'eq', value: 'u-1' },
  ])
  await user.click(screen.getByRole('button', { name: 'Clear all' }))
  expect(onClearAll).toHaveBeenCalled()
})

it('shows a filter that lives outside the column list', async () => {
  const onRemove = vi.fn()
  render(<FilterChips columns={COLUMNS} filters={[]} onRemove={() => {}} onClearAll={() => {}}
                      extra={[{ key: 'flag', label: 'Type', text: 'Clients', onRemove }]} />)
  await userEvent.setup().click(screen.getByRole('button', { name: /Remove the Type filter/ }))
  expect(onRemove).toHaveBeenCalled()
})
