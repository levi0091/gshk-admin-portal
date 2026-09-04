import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AuditLogPage from './AuditLogPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn() } }))
import { api } from '../lib/api.js'

const PAYLOAD = {
  total: 226351,
  page: 1,
  page_size: 100,
  entries: [
    {
      // imported Viewpoint row — action_type is a useless placeholder
      id: 'l1', created_at: '2026-06-18T12:07:00Z',
      action_type: 'LEGACY_VP_EVENT', source: 'viewpoint_import',
      event_code: 'OFA', created_by: 'JAC', user_display_name: 'JAC', case_id: 'e1',
      // denormalized by migration 012 — generic action + company name
      action_label: 'Statutory Officer (Director/Secretary) Appointment',
      company_name: 'iTutors Limited',
      module: 'body_corporate', subject_kind: 'company',
      subject_id: 'e1', subject_ref: '69123456',
      new_value: 'Get Started HK Limited (company_secretary)',
      metadata: { description: 'Get Started HK Limited Appointed as Secretary' },
    },
    {
      // imported STATUS row — no description, but carries descr + new_value
      id: 'l2', created_at: '2026-06-18T12:07:00Z',
      action_type: 'LEGACY_VP_EVENT', source: 'viewpoint_import',
      event_code: 'STATUS', created_by: 'LEEANN', user_display_name: 'LEEANN',
      source_keycode: '1450PO', action_label: 'Status Changed',
      old_value: '', new_value: 'NC',
      metadata: { descr: 'Not Yet Classified' },
    },
    {
      // native G-FlowDesk field edit
      id: 'n1', created_at: '2026-07-11T09:00:00Z',
      action_type: 'CASE_FIELD_UPDATED', source: 'g_flowdesk',
      event_code: 'ADC', action_label: 'Change Master File Details',
      user_display_name: 'Levi Z.', case_id: 'e2',
      company_name: 'Harbour Tech',
      module: 'body_corporate', subject_kind: 'company', subject_id: 'e2',
      before_state: { field: 'company_name', old: 'Old Co' },
      after_state: { field: 'company_name', new: 'New Co' },
      metadata: null,
    },
    {
      // NAR1 workflow — the case number leads, the company qualifies it
      id: 'n2', created_at: '2026-09-04T09:00:00Z',
      action_type: 'CASE_STATUS_CHANGED', source: 'g_flowdesk',
      event_code: 'CASE_STATUS_CHANGED', action_label: 'Case Status Changed',
      user_display_name: 'Roy T.', case_id: 'e3',
      company_name: 'Kanenas Holding Limited',
      module: 'post_incorporation', subject_kind: 'case',
      subject_id: 'c9', subject_ref: 'NAR1-2026-0042',
      new_value: 'Client Verification',
    },
    {
      // a natural person — this row used to name nobody at all
      id: 'n3', created_at: '2026-09-04T09:30:00Z',
      action_type: 'PERSON_FIELD_UPDATED', source: 'g_flowdesk',
      event_code: 'CPC', action_label: 'Change Compliance Details',
      user_display_name: 'Vanis L.',
      company_name: 'Ilze TSERKEZIS',
      module: 'natural_person', subject_kind: 'person',
      subject_id: 'p7', subject_ref: 'A123456(7)',
      before_state: { field: 'passport_no', old: 'X1' },
      after_state: { field: 'passport_no', new: 'X2' },
    },
  ],
}

const renderPage = () => render(<MemoryRouter><AuditLogPage /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
})

describe('AuditLogPage', () => {
  it('shows the GENERIC action, never the placeholder or the per-record description', async () => {
    renderPage()
    await screen.findByText('Statutory Officer (Director/Secretary) Appointment')
    expect(screen.queryByText('LEGACY_VP_EVENT')).not.toBeInTheDocument()
    // the per-record description must NOT be the action — it can't be grouped
    expect(screen.queryByText('Get Started HK Limited Appointed as Secretary')).not.toBeInTheDocument()
    expect(screen.getByText('OFA')).toBeInTheDocument()
  })

  it('sorts server-side from the column headers', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.click(screen.getByRole('columnheader', { name: /Case \/ Company \/ Person/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=company_name'))).toBe(true)
    })
  })

  it('resolves the case to a company name and links to it', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('iTutors Limited'))
    expect(navigate).toHaveBeenCalledWith('/companies/e1')
  })

  it('falls back to the Viewpoint key when no company resolves', async () => {
    renderPage()
    await screen.findByText('1450PO')
    expect(screen.getByText('1450PO')).toBeInTheDocument()
  })

  it('shows what changed for a native field edit', async () => {
    renderPage()
    await screen.findByText('Change Master File Details')
    const row = screen.getByText('Harbour Tech').closest('tr')
    expect(within(row).getByText('Old Co')).toBeInTheDocument()
    expect(within(row).getByText('New Co')).toBeInTheDocument()
  })

  it('renders a STATUS row change', async () => {
    renderPage()
    await screen.findByText('Status Changed')
    const row = screen.getByText('1450PO').closest('tr')
    expect(within(row).getByText('NC')).toBeInTheDocument()
  })

  it('shows the acting user, falling back to the Viewpoint actor', async () => {
    renderPage()
    await screen.findByText('iTutors Limited')
    expect(screen.getByText('Levi Z.')).toBeInTheDocument()
    expect(screen.getByText('JAC')).toBeInTheDocument()
  })

  it('filters to native G-FlowDesk events', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.click(screen.getByRole('tab', { name: 'G-FlowDesk' }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('source=g_flowdesk'))).toBe(true)
    })
  })

  it('debounces search to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.type(screen.getByLabelText('Search company, person, reference, action or user'), 'secretary')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=secretary'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('renders an error state', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load audit log: boom/)).toBeInTheDocument()
  })
})

// Same race as the dashboard (UAT W-8). This page pages through 226k rows, so
// a slow response landing after a newer one is more likely here, not less.
describe('AuditLogPage — overlapping requests (UAT W-8)', () => {
  function deferred() {
    let resolve, reject
    const promise = new Promise((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
  }

  async function toggleTo(tabName) {
    const user = userEvent.setup()
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    renderPage()
    await user.click(screen.getByRole('tab', { name: tabName }))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    return { first, second }
  }

  it('does not report a failure from a request the user has already moved past', async () => {
    const { first, second } = await toggleTo(/G-FlowDesk/)
    first.reject(new Error('boom'))
    second.resolve(PAYLOAD)
    await waitFor(() => expect(screen.queryByText('Loading…')).not.toBeInTheDocument())
    expect(screen.queryByText(/Failed to load audit log/)).not.toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo(/G-FlowDesk/)
    const signal = api.get.mock.calls[0][1]?.signal
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(signal.aborted).toBe(true)
    expect(api.get.mock.calls[1][1].signal.aborted).toBe(false)
  })

  it('aborts the in-flight request when the page unmounts', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderPage()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    const { signal } = api.get.mock.calls[0][1]
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})


// ---- WHICH module, WHICH record (migration 034) ---------------------------
//
// Levi 2026-09-04: "in a lot of actions it is not clear what case or company or
// person it is referring to." Each of these is one of the readings that was
// missing.
describe('AuditLogPage — the subject and the module', () => {
  it('names the module a change belongs to', async () => {
    renderPage()
    await screen.findByText('iTutors Limited')
    expect(screen.getByText('Post-incorporation')).toBeInTheDocument()
    expect(screen.getByText('Natural Person')).toBeInTheDocument()
    expect(screen.getAllByText('Body Corporate').length).toBeGreaterThan(0)
  })

  it('reads a body corporate as name (BRN)', async () => {
    renderPage()
    const row = (await screen.findByText('iTutors Limited')).closest('tr')
    expect(within(row).getByText('(69123456)')).toBeInTheDocument()
    expect(within(row).getByText('Company')).toBeInTheDocument()
  })

  it('reads a NAR1 workflow row as case no (company), linking to the CASE', async () => {
    const user = userEvent.setup()
    renderPage()
    const caseNo = await screen.findByText('NAR1-2026-0042')
    const row = caseNo.closest('tr')
    expect(within(row).getByText('(Kanenas Holding Limited)')).toBeInTheDocument()
    expect(within(row).getByText('Case')).toBeInTheDocument()
    await user.click(caseNo)
    expect(navigate).toHaveBeenCalledWith('/cases/c9')
  })

  it('reads a natural person as name (identity number), linking to the person', async () => {
    const user = userEvent.setup()
    renderPage()
    const name = await screen.findByText('Ilze TSERKEZIS')
    const row = name.closest('tr')
    expect(within(row).getByText('(A123456(7))')).toBeInTheDocument()
    expect(within(row).getByText('Person')).toBeInTheDocument()
    await user.click(name)
    expect(navigate).toHaveBeenCalledWith('/persons/p7')
  })

  it('shows a dash for a Viewpoint row with no module — never an invented one', async () => {
    // Viewpoint recorded no NAR1 workflow, no document store and no CR filing.
    renderPage()
    const row = (await screen.findByText('1450PO')).closest('tr')
    expect(within(row).getByText('—')).toBeInTheDocument()
  })
})

describe('AuditLogPage — per-column filters', () => {
  async function openFilter(columnName) {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    const header = screen.getByRole('columnheader', { name: new RegExp(columnName) })
    await user.click(within(header).getByRole('button', { name: /Filter/i }))
    return user
  }

  it('sends the module filter to the SERVER, not to the 100 rows on screen', async () => {
    const user = await openFilter('Module')
    await user.click(screen.getByLabelText('Natural Person'))
    await user.click(screen.getByRole('button', { name: /Apply/i }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(
        c => c[0].includes('filter=module%3Ain%3Anatural_person'))).toBe(true)
    })
  })

  it('names every applied filter in a removable chip', async () => {
    const user = await openFilter('Module')
    await user.click(screen.getByLabelText('CR Filing'))
    await user.click(screen.getByRole('button', { name: /Apply/i }))
    const chip = await screen.findByRole('button', { name: /Remove the Module filter/ })
    expect(chip).toHaveTextContent('CR Filing')
    await user.click(chip)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Remove the Module filter/ }))
        .not.toBeInTheDocument()
    })
  })

  it('filters the subject by name', async () => {
    const user = await openFilter('Case \\/ Company \\/ Person')
    await user.type(screen.getByPlaceholderText('Company, person or case'), 'kanenas')
    await user.click(screen.getByRole('button', { name: /Apply/i }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(
        c => c[0].includes('company_name%3Acontains%3Akanenas'))).toBe(true)
    })
  })
})


// ---- the row that took the whole screen down -----------------------------
//
// React error #31: "objects are not valid as a React child". Thrown DURING
// RENDER, so it does not blank one cell — it blanks the Audit Log. One row on
// page 1 was enough, and it reached DEV.
//
// `before_state`/`after_state` are free-form JSONB written by ~50 call sites
// over two years. The page has to survive whatever history contains, so these
// test the boundary, not the one caller that tripped it.
describe('AuditLogPage — a value that is not a string (react-error-31)', () => {
  const withEntry = entry => ({ ...PAYLOAD, entries: [entry] })

  const SHARE_CLASS = {
    id: 'x1', created_at: '2026-09-04T06:32:03Z', source: 'g_flowdesk',
    action_type: 'CASE_FIELD_UPDATED', event_code: 'COC',
    action_label: 'Change Entity Statutory Information',
    company_name: 'ABC Testing Limited', case_id: 'e9',
    user_display_name: 'Levi Z.',
    // Exactly what POST /companies/{id}/share-classes wrote on DEV.
    after_state: {
      field: 'share_class',
      new: {
        currency: 'HKD', class_name: 'Ordinary', total_paid: '10000',
        total_issued: '10000', issued_amount: '10000',
      },
    },
  }

  it('renders the row instead of crashing the page', async () => {
    api.get.mockResolvedValue(withEntry(SHARE_CLASS))
    renderPage()
    // The page rendered at all — before the fix this threw and the error
    // boundary replaced everything with "This screen failed to render".
    expect(await screen.findByText('ABC Testing Limited')).toBeInTheDocument()
    expect(screen.queryByText(/failed to render/i)).not.toBeInTheDocument()
  })

  it('spells the object out rather than dropping it', async () => {
    api.get.mockResolvedValue(withEntry(SHARE_CLASS))
    renderPage()
    const row = (await screen.findByText('ABC Testing Limited')).closest('tr')
    // Every value the operator needs is still on screen, keyed by its field.
    expect(within(row).getByText(/class name: Ordinary/)).toBeInTheDocument()
    expect(within(row).getByText(/currency: HKD/)).toBeInTheDocument()
    expect(within(row).getByText(/issued amount: 10000/)).toBeInTheDocument()
  })

  it('survives an array, a number, a boolean and a nested object', async () => {
    // None of these exist in DEV today. That is the point: the next call site
    // to write one must not be able to take the screen down.
    const shapes = [
      { field: 'recipients', new: ['a@x.com', 'b@x.com'] },
      { field: 'mortgages_total', new: 0 },
      { field: 'aoa_agm_waived', new: false },
      { field: 'address', new: { line1: 'Unit 5', city: { name: 'HK' } } },
    ]
    for (const [i, after_state] of shapes.entries()) {
      api.get.mockResolvedValue(withEntry({
        ...SHARE_CLASS, id: `s${i}`, after_state,
      }))
      const { unmount } = renderPage()
      expect(await screen.findByText('ABC Testing Limited')).toBeInTheDocument()
      expect(screen.queryByText(/failed to render/i)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('still shows a plain string change unchanged', async () => {
    // The coercion must not disturb the ordinary case, which is every other row.
    api.get.mockResolvedValue(withEntry({
      ...SHARE_CLASS,
      before_state: { field: 'company_name', old: 'Old Co' },
      after_state: { field: 'company_name', new: 'New Co' },
    }))
    renderPage()
    const row = (await screen.findByText('ABC Testing Limited')).closest('tr')
    expect(within(row).getByText('Old Co')).toBeInTheDocument()
    expect(within(row).getByText('New Co')).toBeInTheDocument()
  })

  it('renders a flag turned OFF, rather than reading it as no value', async () => {
    // `false` is a real answer here and must survive the coercion.
    api.get.mockResolvedValue(withEntry({
      ...SHARE_CLASS,
      action_type: 'COMPANY_FLAG_CHANGED',
      before_state: { is_client: true },
      after_state: { is_client: false },
    }))
    renderPage()
    const row = (await screen.findByText('ABC Testing Limited')).closest('tr')
    expect(within(row).getByText('true')).toBeInTheDocument()
    expect(within(row).getByText('false')).toBeInTheDocument()
  })
})
