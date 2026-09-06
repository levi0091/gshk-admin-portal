/**
 * Putting a failure back in front of the operator.
 *
 * WHY THIS IS NOT `element.scrollIntoView()`. The app shell does not scroll the
 * window: `#root` is a full-height flex column, the body row is
 * `overflow: hidden`, and the only thing that scrolls is
 * `<main class="app-main">` (AppShell.jsx), which carries `overflowY: auto`
 * inline. So `window.scrollTo` moves nothing at all, and `scrollIntoView` moves
 * whatever the browser decides is the scrolling box — which is fine until a
 * card between the banner and `main` gets an overflow of its own.
 *
 * And `block: 'center'` was answering the wrong question. Centring the banner
 * leaves the crumb, the page title and both status badges above the fold; Levi
 * asked for the top of the page, which is a scroll position, not an alignment.
 *
 * Nothing here may throw. It runs from an effect in the commit that renders the
 * banner, so an exception blanks the very error it exists to reveal.
 */

/** Style reader, injectable so the traversal can be tested without layout. */
const defaultGetStyle = el =>
  (typeof window !== 'undefined' && window.getComputedStyle)
    ? window.getComputedStyle(el)
    : null

/**
 * The nearest ancestor that is BOTH scrollable and actually overflowing.
 *
 * Both halves matter: a card styled `overflow: auto` whose content fits is not
 * where the page scrolls, and stopping at it scrolls nothing while looking like
 * it worked.
 */
export function findScroller(el, getStyle = defaultGetStyle) {
  for (let n = el?.parentElement; n; n = n.parentElement) {
    let overflowY
    try {
      overflowY = getStyle(n)?.overflowY
    } catch {
      overflowY = undefined
    }
    if (/auto|scroll|overlay/.test(overflowY || '')
        && n.scrollHeight > n.clientHeight) {
      return n
    }
  }
  return null
}

/**
 * Scroll `el`'s container to the very top.
 *
 * `win` and `getStyle` are injected only so this can be tested: jsdom reports
 * every element as 0x0 with no overflow, so a test against a rendered tree
 * could exercise nothing but the fallback.
 */
export function scrollToTop(el, options = {}) {
  const {
    getStyle = defaultGetStyle,
    win = typeof window !== 'undefined' ? window : null,
    reduced = Boolean(win?.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches),
  } = options
  const behavior = reduced ? 'auto' : 'smooth'

  try {
    const target = findScroller(el, getStyle) || win
    if (!target) return
    if (typeof target.scrollTo === 'function') target.scrollTo({ top: 0, behavior })
    else target.scrollTop = 0
  } catch {
    // Scrolling is a courtesy. Showing the error is not.
  }
}
