/**
 * The document buckets against the real stylesheet (GSHK 2026-11-21).
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/components/__buckets_visual__.test.jsx
 *   node scripts/shoot-modals.mjs
 */
import { describe, it, vi } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import fs from 'node:fs'
import path from 'node:path'

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() },
}))
vi.mock('../lib/download.js', () => ({ downloadDocument: vi.fn() }))

import DocumentBuckets from './DocumentBuckets.jsx'
import { DEFAULT_LIMITS } from '../lib/documentSections.js'

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const BUCKETS = [
  ['annual_return', 'Annual Return (NAR1)', 'Filed annual returns', ['Filed NAR1']],
  ['corporate_identity', 'Corporate Identity & Due Diligence',
    'Business licence, articles, address proof and AML reports',
    ['Business Licence', 'AoA of Corporate Entity', 'Address Proof', 'AML Case Report']],
  ['br_renewal', 'Business Registration Renewal', 'Renewed business registration', ['Renewed BR']],
  ['maintenance', 'Maintenance', 'Officer changes, transfers and other filed forms',
    ['Filed ND2A', 'Filed ND2B', 'NR1', 'NNC2', 'NSC1', 'Stamped Share Transfer']],
  ['payments', 'Payments', 'Payment slips', ['Payment Slip']],
  ['incorporation', 'Incorporation / Statutory Registers',
    'Incorporation papers and the statutory registers',
    ['Filed NNC1', 'Certificate of Incorporation', 'AoA', 'Register of Members']],
].map(([key, label, description, suggestions]) => ({ key, label, description, suggestions }))
  .concat([{ key: 'other', label: 'Other Documents', description: '', suggestions: [], fallback: true }])

const d = (id, bucket, file_name, uploaded_at, extra = {}) => ({
  id, bucket, file_name, uploaded_at, tags: [], title: null, status: 'active',
  current_version: 1, document_versions: [], ...extra,
})

const DOCS = [
  d('a1', 'annual_return', 'Skyline Capital NAR1 2026 (filed).pdf', '2026-11-02T03:00:00Z',
    { tags: ['Filed NAR1'], current_version: 2, document_versions: [
      { id: 'v1', version_number: 1, created_at: '2025-11-03T03:00:00Z' },
      { id: 'v2', version_number: 2, created_at: '2026-11-02T03:00:00Z' }] }),
  d('c1', 'corporate_identity', 'Business licence 2026.jpg', '2026-10-14T03:00:00Z',
    { title: 'Scanned at front desk', tags: ['Business Licence'] }),
  d('c2', 'corporate_identity', 'AML case report - Skyline.xlsx', '2026-09-30T03:00:00Z',
    { tags: ['AML Case Report'] }),
  ...Array.from({ length: 7 }, (_, i) => d(`p${i}`, 'payments',
    `Payment slip ${String(i + 1).padStart(2, '0')} - HSBC transfer.pdf`,
    `2026-11-${String(20 - i).padStart(2, '0')}T03:00:00Z`,
    i < 2 ? { tags: ['Payment Slip'], title: 'Annual return fee' } : {})),
  d('i1', 'incorporation', 'Certificate of Incorporation.pdf', '2024-05-20T03:00:00Z',
    { tags: ['Certificate of Incorporation'] }),
  d('i2', 'incorporation', 'Register of Members.docx', '2024-05-20T02:00:00Z'),
  d('i3', 'incorporation', 'Onboarding form - signed.msg', '2024-05-19T02:00:00Z'),
]

function freeze(root) {
  for (const el of root.querySelectorAll('input')) {
    if (el.type === 'checkbox') el.toggleAttribute('checked', el.checked)
    else if (el.value) el.setAttribute('value', el.value)
  }
}

function dump(name, node) {
  freeze(node)
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`),
    `<div class="detail-grid"><div>${node.outerHTML}</div></div>`, 'utf8')
}

const ui = () => (
  <DocumentBuckets ownerKind="entity" ownerId="e1" ownerName="Skyline Capital Limited"
                   documents={DOCS} buckets={BUCKETS} limits={DEFAULT_LIMITS}
                   canEdit canRemove canDownload />
)

describe.runIf(SHOOT)('document buckets visual harness', () => {
  it('populated', () => {
    const { container } = render(ui())
    dump('s-buckets-1-populated', container.firstChild)
  })

  it('after a drop, with the bulk bar open', async () => {
    const user = userEvent.setup()
    const { container } = render(ui())
    await user.click(screen.getByRole('checkbox', { name: /Select Payment slip 03/ }))
    await user.click(screen.getByRole('checkbox', { name: /Select Payment slip 04/ }))
    await user.click(screen.getByRole('checkbox', { name: /Select Payment slip 05/ }))
    dump('s-buckets-2-selected', container.firstChild)
  })

  it('drop overlay', async () => {
    const { container } = render(ui())
    act(() => { fireEvent.dragEnter(window, { dataTransfer: { types: ['Files'] } }) })
    await waitFor(() => screen.getByRole('dialog'))
    fireEvent.dragEnter(screen.getByTestId('drop-payments'), { dataTransfer: { types: ['Files'] } })
    fs.mkdirSync(OUT, { recursive: true })
    fs.writeFileSync(path.join(OUT, 'm-buckets-3-overlay.html'),
      container.querySelector('.bk-overlay').outerHTML, 'utf8')
  })
})
