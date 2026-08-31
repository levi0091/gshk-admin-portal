/**
 * NOT a test — a visual harness for AddressBlock, matching the one in
 * components/case/__visual__.test.jsx. Dumps the real component's markup so
 * scripts/shoot-stages.mjs can screenshot it against the real stylesheet.
 *
 * The counter and the shared-address warning are the two things worth LOOKING
 * at: both are meant to be noticed before a save, and whether they are is not
 * a question the JSX can answer.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 * KNOWN ARTIFACT: every <select> shoots as "Select…" regardless of its value.
 * React sets a select's choice as a DOM PROPERTY and `innerHTML` serialises
 * only attributes, so the dump cannot carry it. The country and district
 * selects are correct in the browser and asserted in AddressBlock.test.jsx —
 * do not "fix" the component over this.
 */
import { render } from '@testing-library/react'
import { describe, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import AddressBlock from './AddressBlock.jsx'

const OUT = path.resolve(process.cwd(), '.visual')
const run = process.env.SHOOT === '1' ? describe : describe.skip

const LOOKUPS = {
  cr_district: [
    { code: 'CENTRAL', label: 'CENTRAL' },
    { code: 'WANCHAI', label: 'WANCHAI' },
    { code: 'TSUENWAN', label: 'TSUENWAN' },
  ],
  country: [
    { code: 'HK', label: 'Hong Kong' },
    { code: 'CY', label: 'Cyprus' },
  ],
}

function dump(name, ui) {
  fs.mkdirSync(OUT, { recursive: true })
  const { container } = render(ui)
  fs.writeFileSync(path.join(OUT, `address-${name}.html`), container.innerHTML)
}

run('AddressBlock visual', () => {
  it('the shared GSHK registered office, as 4,446 companies see it', () => {
    dump('shared', (
      <div className="card">
        <div className="tile-sec-lbl">Registered Office</div>
        <AddressBlock
          lookups={LOOKUPS}
          onChange={() => {}}
          value={{
            line1: 'Suite C, Level 7', line2: 'World Trust Tower',
            line3: '50 Stanley Street, Central', city: 'CENTRAL',
            country: 'HK', shared_by: 4446,
          }}
        />
      </div>
    ))
  })

  it('an overseas director whose address CR would refuse', () => {
    dump('over-limit', (
      <div className="card">
        <div className="tile-sec-lbl">Residential Address</div>
        <AddressBlock
          lookups={LOOKUPS}
          onChange={() => {}}
          value={{
            line1: '', line2: '',
            line3: 'M. Floor House-15, 16, Sultan Bin Khalifa Al Habtoor Bldg, 127-44C ST DM.65',
            city: 'Dubai', country: 'CY', shared_by: 1,
          }}
        />
      </div>
    ))
  })

  it('read-only, as it appears on a profile', () => {
    dump('readonly', (
      <div className="card">
        <div className="tile-sec-lbl">Registered Office</div>
        <div className="kv-list">
          <AddressBlock
            readOnly
            value={{
              line1: 'Suite C, Level 7', line2: 'World Trust Tower',
              line3: '50 Stanley Street, Central', city: 'CENTRAL',
              country: 'HK', shared_by: 4446,
            }}
          />
        </div>
      </div>
    ))
  })
})
