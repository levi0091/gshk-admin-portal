import { describe, it, expect, vi } from 'vitest'
import { findScroller, scrollToTop } from './scroll.js'

/**
 * Fake DOM nodes. jsdom reports every element as 0x0 with no overflow, so a
 * test against a rendered tree could only ever exercise the fallback — which is
 * exactly the branch that was never the problem.
 */
function node(over) {
  return {
    overflowY: 'visible', scrollHeight: 0, clientHeight: 0, scrollTop: 0,
    parentElement: null, ...over,
  }
}

/** The injected reader, standing in for window.getComputedStyle. */
const styleOf = n => ({ overflowY: n.overflowY })

function chain(...nodes) {
  nodes.reduce((child, parent) => { child.parentElement = parent; return parent })
  return nodes[0]
}

describe('findScroller', () => {
  it('finds the ancestor that actually scrolls, not the first one styled to', () => {
    // The real shape: AppShell's <main class="app-main"> is overflowY:auto and
    // taller than its box; nothing between it and the banner scrolls.
    const main = node({ overflowY: 'auto', scrollHeight: 2400, clientHeight: 800 })
    const banner = chain(node(), node(), main)
    expect(findScroller(banner, styleOf)).toBe(main)
  })

  it('skips an overflow container that is not overflowing', () => {
    // A card with `overflow: hidden` or an auto container whose content fits is
    // not where the page scrolls, and stopping there scrolls nothing.
    const card = node({ overflowY: 'auto', scrollHeight: 300, clientHeight: 300 })
    const main = node({ overflowY: 'auto', scrollHeight: 2400, clientHeight: 800 })
    const banner = chain(node(), card, main)
    expect(findScroller(banner, styleOf)).toBe(main)
  })

  it('returns null when nothing in the chain scrolls', () => {
    expect(findScroller(chain(node(), node()), styleOf)).toBeNull()
  })

  it('does not blow up on a detached element', () => {
    expect(findScroller(null, styleOf)).toBeNull()
  })
})

describe('scrollToTop', () => {
  it('puts the scroller at the very top', () => {
    // Not scrollIntoView({block:"center"}): the banner sits under the page
    // header and the crumb, so centring it leaves the top of the page — and
    // half the reason for the failure — above the fold. Levi asked for the top.
    const scrollTo = vi.fn()
    const main = node({
      overflowY: 'auto', scrollHeight: 2400, clientHeight: 800,
      scrollTop: 1600, scrollTo,
    })
    scrollToTop(chain(node(), main), { getStyle: styleOf })
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
  })

  it('jumps rather than glides when the viewer asked for less motion', () => {
    const scrollTo = vi.fn()
    const main = node({
      overflowY: 'auto', scrollHeight: 2400, clientHeight: 800, scrollTo,
    })
    scrollToTop(chain(node(), main), { getStyle: styleOf, reduced: true })
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'auto' })
  })

  it('assigns scrollTop when the element has no scrollTo', () => {
    const main = node({
      overflowY: 'auto', scrollHeight: 2400, clientHeight: 800, scrollTop: 900,
    })
    scrollToTop(chain(node(), main), { getStyle: styleOf })
    expect(main.scrollTop).toBe(0)
  })

  it('falls back to the window when no ancestor scrolls', () => {
    const win = { scrollTo: vi.fn() }
    scrollToTop(chain(node(), node()), { getStyle: styleOf, win })
    expect(win.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
  })

  it('never throws, whatever it is handed', () => {
    // This runs inside the commit that renders the error banner. An exception
    // here would blank the very error it exists to reveal — which is how three
    // unrelated tests went dark the first time this was written.
    expect(() => scrollToTop(null, { getStyle: styleOf, win: null })).not.toThrow()
    expect(() => scrollToTop({}, {
      getStyle: () => { throw new Error('x') }, win: null,
    })).not.toThrow()
    const hostile = { scrollTo: () => { throw new Error('boom') } }
    expect(() => scrollToTop(chain(node(), node()),
                             { getStyle: styleOf, win: hostile })).not.toThrow()
  })
})
