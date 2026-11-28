// `persons.address_on_forms` (migration 067, Levi 2026-11-28): which address a
// natural person's forms print where CR asks for a correspondence address, and
// in NAR1's Schedule 1, the public register of members. Correspondence is the
// default because clients often do not want their home address on a public
// form; with no correspondence address on record the residential one is
// printed anyway.
//
// One descriptor, shared by the Person Profile and the New Person form, so the
// two cannot word the choice differently (Add and Edit offer the same fields).
export const ADDRESS_ON_FORMS_FIELD = {
  key: 'address_on_forms',
  label: 'Address shown on forms (NAR1, ND2A, ND2B)',
  type: 'choice',
  full: true,
  default: 'correspondence',
  options: [
    { code: 'correspondence', label: 'Correspondence address (residential if none on record)' },
    { code: 'residential', label: 'Residential address' },
  ],
  hint: 'Used for the correspondence address on NAR1, ND2A and ND2B, and for this person’s line in NAR1 Schedule 1.',
}
