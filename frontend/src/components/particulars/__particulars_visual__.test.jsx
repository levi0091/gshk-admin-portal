/**
 * NOT a test — a visual harness for the by-company cards (Levi 2026-10-05),
 * twin of `__nd2_feedback_visual__.test.jsx`. Skipped unless SHOOT=1.
 *
 *   SHOOT=1 SHOOT_OUT=/some/dir npx vitest run src/components/particulars/__particulars_visual__.test.jsx
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import ParticularsByCompany from './ParticularsByCompany.jsx'

const BOOK = {
  companies: [{ entity_id: 'e-kanenas', company_name: 'Kanenas Holding Limited', roles: ['director'] },
              { entity_id: 'e-zenith', company_name: 'ZenithStream Limited', roles: ['director', 'company_secretary'] },
              { entity_id: 'e-harbour', company_name: 'Harbour Lane Trading Limited', roles: ['director'] }],
  default_residential_address_id: 'a1',
  residential: [
    { address_id: 'a1', is_default: true, used_by: ['e-kanenas', 'e-harbour'],
      address: { line1: 'Flat A, 10/F', line2: 'Harbour View', line3: "1 Queen's Road", city: 'CENTRAL', country: 'HK' } },
    { address_id: 'a2', is_default: false, used_by: ['e-zenith'],
      address: { line1: '12 Rue de Rivoli', city: 'PARIS', postal_code: '75001', country: 'FR' } },
  ],
  correspondence: [{ address_id: 'a3', used_by: ['e-kanenas'],
    address: { line1: 'Room 1201', line2: 'Tower 2', line3: '8 Connaught Place', city: 'CENTRAL', country: 'HK' } }],
  correspondence_same_as_residential: ['e-zenith', 'e-harbour'],
  identity: [
    { document_id: 'd1', id_type: 'passport', id_number: '18FV22917', issuing_country: 'FR', is_primary: true,
      used_by: ['e-kanenas', 'e-harbour'] },
    { document_id: 'd2', id_type: 'passport', id_number: '567201934', issuing_country: 'US', is_primary: false,
      used_by: ['e-zenith'] },
  ],
}
vi.mock('../../lib/api.js', () => ({
  api: { get: vi.fn(() => Promise.resolve(BOOK)), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))
const LOOKUPS = { cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'FR', label: 'France' },
  { code: 'US', label: 'United States of America' }] }
const SHOOT = process.env.SHOOT === '1'
const OUT = path.resolve(process.env.SHOOT_OUT || path.join(process.cwd(), '.visual'))
const write = (name, html) => {
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), html)
}

describe.skipIf(!SHOOT)('by-company cards — visual dump', () => {
  it('dumps the cards and both dialogs', async () => {
    const user = userEvent.setup()
    const { container } = render(<ParticularsByCompany personId="p1" canEdit lookups={LOOKUPS} />)
    await screen.findByRole('region', { name: 'Residential addresses' })
    write('particulars-cards', container.innerHTML)
    const ids = screen.getByRole('region', { name: 'Identification by company' })
    await user.click(within(within(ids).getByText('567201934').closest('[data-entry]'))
      .getByRole('button', { name: 'Companies…' }))
    write('particulars-picker', document.querySelector('.overlay').outerHTML)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    const res = screen.getByRole('region', { name: 'Residential addresses' })
    await user.click(within(res).getByRole('button', { name: 'New' }))
    write('particulars-new', document.querySelector('.overlay').outerHTML)
  })
})
