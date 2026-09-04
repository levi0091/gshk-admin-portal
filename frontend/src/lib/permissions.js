/**
 * How a screen says "not for you" about one control.
 *
 * DISABLED, NOT HIDDEN, on the profile screens (Levi 2026-09-04: "I should
 * only be able to click around the company profile but all these buttons
 * should be disabled for me"). Hiding a control answers a question nobody
 * asked; a disabled one with a reason on it says the feature exists, you are
 * reading a real screen, and here is what to request.
 *
 * The string names the MODULE AND LEVEL because that is what a Super Admin
 * types into Roles. "Ask an administrator for access" makes the administrator
 * guess too.
 */
export function needsPermission(module, permission) {
  return `Requires ${module} (${permission}) — your role does not have it`
}

/** `title` for a control, or undefined when the user may use it. */
export function disabledReason(allowed, module, permission) {
  return allowed ? undefined : needsPermission(module, permission)
}
