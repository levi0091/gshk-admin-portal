// An address in the Companies Registry's own five lines (Jacqueline B3,
// 2026-10-01: "Please list the address format"). The labels are CR's wording on
// its forms, verbatim, so what an operator reads on screen is what the client
// reads on the ND2A/ND2B and what CR receives. `nar1_mapper._address` is the
// other half of this contract: the district line absorbs city, region and
// postcode, because CR has one box for all three.

export const CR_ADDRESS_LABELS = [
  'Flat/Floor/Block etc.',
  'Building (Name)',
  'Street/Estate/Lot/Village etc.',
  'District/City/Province/State/Postal Code etc.',
  'Country/Region',
]

/** The country's name from CR's own list, or the stored value as it stands. */
export function countryName(code, lookups) {
  if (!code) return ''
  const hit = (lookups?.cr_country || []).find(o => o.code === code)
  return hit?.label || code
}

/** `[{label, value}]` in CR's order; `value` is '' for an empty line. */
export function crAddressLines(address, lookups) {
  const a = address || {}
  const district = [a.city, a.state_region, a.postal_code].filter(Boolean).join(' ')
  const values = [a.line1 || '', a.line2 || '', a.line3 || '', district,
                  countryName(a.country, lookups)]
  return CR_ADDRESS_LABELS.map((label, i) => ({ label, value: values[i] }))
}
