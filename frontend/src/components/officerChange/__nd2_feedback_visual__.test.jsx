/**
 * NOT a test — a visual harness for the pieces Jacqueline's feedback (1 Oct
 * 2026) added to the ND2A/ND2B screens, twin of `__cases_visual__.test.jsx`.
 * Dumps each component's markup so a script can screenshot it against the real
 * stylesheets. Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 SHOOT_OUT=/some/dir npx vitest run src/components/officerChange/__nd2_feedback_visual__.test.jsx
 */
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import RulesPanel from './RulesPanel.jsx'
import ManualChecks from './ManualChecks.jsx'
import EffectiveDatesPanel from './EffectiveDatesPanel.jsx'
import AttachmentsCard from './AttachmentsCard.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import ChangesCard from './ChangesCard.jsx'
import OtherOpenCases from '../case/OtherOpenCases.jsx'

vi.mock('../../lib/api.js', () => ({
  api: { get: vi.fn(() => Promise.resolve({})), post: vi.fn(), patch: vi.fn(), put: vi.fn(),
         del: vi.fn(), upload: vi.fn(), blob: vi.fn() },
}))

const SHOOT = process.env.SHOOT === '1'
const OUT = path.resolve(process.env.SHOOT_OUT || path.join(process.cwd(), '.visual'))
const ALL = { write: true, tpsiWrite: true, tpsiSubmit: true, tpsiRead: true }

const dump = (name, ui) => {
  const { container } = render(<MemoryRouter>{ui}</MemoryRouter>)
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), container.innerHTML)
}

const CASE = {
  id: 'k1', case_no: 'ND2A-2026-0007', form_code: 'Nd2a', case_type: 'ND2A', editable: true,
  officers: [], documents: [
    { id: 'd1', entry_id: null, file_name: 'Written-resolution-signed.pdf', type_label: 'Board resolution',
      send_with_email: true },
    { id: 'd2', entry_id: null, file_name: 'Cover-note.pdf', type_label: 'Other supporting document',
      send_with_email: false }],
  attach_resolution: false,
  entries: [
    { id: 'n1', kind: 'cessation', capacity: 'director', party: { name: 'WONG Mei Ling' },
      summary: 'Director · ceases 12 Sep 2026 · Resignation / Others' },
    { id: 'n2', kind: 'appointment', capacity: 'director', party: { name: 'LEE Ka Ho' },
      summary: 'Director · appointed date not set', consent_mode: 'econsent',
      econsent: { sent: true, signed_at: null }, date_deferred: true },
    { id: 'n3', kind: 'appointment', capacity: 'director', party: { name: 'CHAN Siu Ming' },
      summary: 'Director · appointed 12 Sep 2026', consent_mode: 'esign' },
  ],
  rules: {
    blocking: false,
    lines: ['After these changes the company will have 2 directors (2 natural persons) and 1 secretary.',
            'Directors: LEE Ka Ho and CHAN Siu Ming.',
            'A company secretary remains — Get Started HK Limited.'],
    checks: [
      { code: 'has_changes', ok: true, level: 'rule', text: 'There are changes to file.' },
      { code: 'dates_present', ok: false, level: 'notice',
        text: '1 change has no effective date yet — enter it at Signing.' },
    ],
  },
  manual_checks: [
    { code: 'kyc', entry_id: 'n2', label: 'KYC / WorldCheck cleared — LEE Ka Ho', kind: 'tick', ok: true },
    { code: 'resignation_letter', entry_id: 'n1', label: 'Resignation letter on file — WONG Mei Ling',
      kind: 'document', ok: true, document: { file_name: 'resignation-letter-wong-mei-ling.pdf',
        uploaded_at: '2026-09-15T02:00:00Z' } },
    { code: 'written_resolution', entry_id: null, label: 'Signed written resolution on file',
      kind: 'document', ok: false, document: null },
  ],
  dates_missing: ['LEE Ka Ho'],
  other_open_cases: [{ id: 'c9', case_no: 'NAR-2026-0042', case_type: 'NAR1', form_code: 'Nar1',
    workflow_status: { label: 'Awaiting client' } }],
}

const OLD = { line1: '', line2: 'Harbour Vista', line3: '9 Model Road', city: 'NORTHPOINT', country: 'HK' }
const NEW = { line1: 'Flat 20A, Tower 1', line2: 'Harbour Vista', line3: '9 Model Road',
              city: 'NORTHPOINT', country: 'HK' }
const ND2B = { ...CASE, form_code: 'Nd2b', case_type: 'ND2B', anniversary_default: '2026-03-12',
  entries: [{ id: 'm1', kind: 'change', capacity: 'director', officer_id: 'o1',
    party: { name: 'CHAN Tai Man', profile_path: '/persons/p1' }, items: [
      { key: 'residential_address', cr_item: 'd', label: 'Residential address', old: OLD, new: NEW,
        effective_date: '2026-03-12' },
      { key: 'email', cr_item: 'f', label: 'Email address', old_text: 'taiman.chan@example.com',
        new_text: 'tm.chan@example.net', effective_date: '2026-03-12' }] }] }

describe.skipIf(!SHOOT)('ND2 feedback visual harness', () => {
  it('dumps', () => {
    dump('rules', <RulesPanel rules={CASE.rules} />)
    dump('manual-checks', <ManualChecks data={CASE} reload={vi.fn()} can={ALL} />)
    dump('effective-dates', <EffectiveDatesPanel data={CASE} reload={vi.fn()} can={ALL} />)
    dump('attachments', <AttachmentsCard data={CASE} reload={vi.fn()} can={ALL} />)
    dump('changes-card', <ChangesCard data={CASE} reload={vi.fn()} can={ALL} />)
    dump('nd2b-card', <ParticularsChangeCard data={ND2B} reload={vi.fn()} can={ALL} />)
    dump('other-open-cases', <OtherOpenCases cases={CASE.other_open_cases} />)
  })
})
