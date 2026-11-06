/**
 * The three capacities an officer can hold, in the words the screens use.
 *
 * ONE MAP, because five components used to carry their own copy of
 * `{ director, company_secretary }` and an alternate director (Jacqueline
 * 2026-11-04, PBI-70: "Alternate directors are not out of scope. We can still
 * provide the service if client requests.") would otherwise have been added to
 * four of them. The keys are the API's `capacity` / `entity_officers.role`
 * values; CR's own code for an alternate is `AD`, which only the backend writes.
 */
export const CAPACITY_LABEL = {
  director: 'Director',
  company_secretary: 'Company Secretary',
  alternate_director: 'Alternate Director',
}

export const capacityLabel = capacity => CAPACITY_LABEL[capacity] || capacity || ''

/**
 * "Alternate Director (alternate to CHAN Tai Man)" for an alternate, the plain
 * capacity for anybody else. `officer` is anything carrying a `role` or
 * `capacity` and, for an alternate, `alternate_to_name`.
 */
export function capacityWithPrincipal(officer) {
  const capacity = officer?.role || officer?.capacity
  const label = capacityLabel(capacity)
  return capacity === 'alternate_director' && officer.alternate_to_name
    ? `${label} (alternate to ${officer.alternate_to_name})` : label
}
