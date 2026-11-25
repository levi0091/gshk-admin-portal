//: NAR1 section 8 (migration 064). GSHK's default is "Not use": the company
//: phone is on the profile for staff to ring, and goes on the public return
//: only when somebody ticks this. One descriptor, so the New Company form and
//: the profile cannot word it differently.
export const NAR1_PHONE_FIELD = {
  key: 'nar1_show_phone',
  label: 'Show this phone on the NAR1 (section 8)',
  type: 'checkbox',
  full: true,
}

/** What the read-only profile says, in GSHK's own words for the default. */
export function nar1PhoneLabel(company) {
  return company?.nar1_show_phone === true ? 'Shown on NAR1' : 'Not used on NAR1'
}
