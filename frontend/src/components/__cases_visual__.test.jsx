/**
 * NOT a test — a visual harness for the company profile's Cases pane, twin of
 * `__modals_visual__.test.jsx`. Renders the real `CasesPane` inside a card at
 * the profile's right-column width (384px, `.detail-grid`) and dumps the markup
 * so `scripts/shoot-stages.mjs` can screenshot it against the real stylesheet.
 *
 * Skipped unless SHOOT=1, so it never runs in CI. Point CASES_JSON at a file
 * holding a real `cases` payload (`{nar1: [...], nnc1: [...]}` from
 * GET /companies/{id}) to shoot real data; otherwise it shoots one case in
 * every state.
 *
 *   SHOOT=1 npx vitest run src/components/__cases_visual__.test.jsx
 *   node scripts/shoot-stages.mjs
 */
import { render } from '@testing-library/react'
import { describe, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import CasesPane, { caseSummary } from './CasesPane.jsx'

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const at = (days, hour = 3) => new Date(Date.UTC(2026, 8, 19 - days, hour, 41)).toISOString()
const row = (n, year, code, label, extra = {}) => ({
  id: `c${n}`, case_no: `NAR-2026-00${n}`, return_year: year,
  workflow_status: { code, label, off_portal: false, cr_text: extra.cr_text || null },
  created_by_name: 'Levi Z.', created_at: at(20 + n), updated_at: at(n, 9),
  ...extra,
})

const EVERY_STATE = {
  nar1: [
    row(81, null, 'client_verification', 'Client Verification', { created_by_name: 'roy' }),
    row(70, 2026, 'awaiting_client', 'Awaiting Client'),
    row(58, 2025, 'client_rejected', 'Client Rejected'),
    row(64, 2024, 'data_verification', 'Data Verification'),
    row(53, 2023, 'signing', 'Signing'),
    row(52, 2022, 'submission', 'Submission'),
    row(49, 2026, 'cr_pending', 'Pending at CR', { cr_text: 'Lodged' }),
    row(31, 2021, 'cr_approved', 'Approved by CR'),
    row(12, 2025, 'cr_registered', 'Registered by CR', { cr_text: 'Registered' }),
    row(80, 2024, 'closed', 'Closed', {
      closed_at: at(1, 16), closed_by_name: 'Levi Z.', closed_reason: 'gonna restart',
    }),
    row(11, 2020, 'cr_rejected', 'Rejected by CR', { cr_text: 'Rejected' }),
  ],
  nnc1: [],
}

function Card({ cases }) {
  const count = (cases.nar1?.length || 0) + (cases.nnc1?.length || 0)
  return (
    <div style={{ width: 384 }}>
      <div className="card">
        <div className="card-hdr">
          <div>
            <div className="card-title">Cases <span className="count-pill">{count}</span></div>
            <div className="card-sub">{caseSummary(cases) || 'NAR1 & NNC1 workflow cases'}</div>
          </div>
          <button className="btn btn-outline btn-sm">+ New case</button>
        </div>
        <CasesPane cases={cases} onOpen={() => {}} />
      </div>
    </div>
  )
}

describe.runIf(SHOOT)('cases pane — visual dump', () => {
  it('dumps the pane', () => {
    fs.mkdirSync(OUT, { recursive: true })
    const real = process.env.CASES_JSON
    const cases = real ? JSON.parse(fs.readFileSync(real, 'utf8')) : EVERY_STATE
    const { container } = render(<Card cases={cases} />)
    fs.writeFileSync(path.join(OUT, real ? 'cases-real.html' : 'cases-every-state.html'),
      container.innerHTML)
  })
})
