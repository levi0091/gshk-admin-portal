import { Component } from 'react'

/**
 * Turns a render crash into something a person can read and report.
 *
 * React unmounts the ENTIRE tree when a render throws. With no boundary that
 * produces a blank white page, no failed network request, and nothing on screen
 * — the error exists only in the browser console, which most people never open.
 * That is precisely how the admin-dev dashboard failure presented: every
 * request 200, nothing rendered, nothing to go on.
 *
 * A class component on purpose: componentDidCatch and getDerivedStateFromError
 * have no hook equivalent. This is the one place in the app that needs one.
 *
 * It deliberately shows the message and stack ON SCREEN. This is an internal
 * staff tool, not a public site — the people who see this are the people who
 * need to report it, and a stack trace they can copy is worth far more than a
 * polite apology that loses the only evidence.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    // Keep the console record too — it carries the full component stack.
    console.error('Render failed:', error, info?.componentStack)
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div style={{ padding: 28, fontFamily: 'Outfit, sans-serif', color: '#3A4060' }}>
        <div style={{
          maxWidth: 900, background: '#FEF5F5', border: '1px solid #F5A9A9',
          borderRadius: 10, padding: '18px 20px',
        }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: '#C53030', marginBottom: 8 }}>
            This screen failed to render
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.55, marginBottom: 14 }}>
            The rest of the portal is unaffected — reload, or go back to the
            dashboard. If it keeps happening, copy the detail below; it names
            the exact cause.
          </p>

          <pre style={{
            background: '#fff', border: '1px solid #F5D0D0', borderRadius: 6,
            padding: 12, fontSize: 11.5, lineHeight: 1.5, overflowX: 'auto',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: '#C53030',
          }}>
            {String(error?.stack || error?.message || error)}
            {info?.componentStack ? `\n\nComponent stack:${info.componentStack}` : ''}
          </pre>

          <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '8px 16px', borderRadius: 6, border: 'none',
                background: '#242C66', color: '#fff', fontSize: 13,
                fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Reload
            </button>
            <button
              onClick={() => { window.location.href = '/dashboard' }}
              style={{
                padding: '8px 16px', borderRadius: 6, border: '1.5px solid #E2E4ED',
                background: '#fff', color: '#3A4060', fontSize: 13,
                fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Back to dashboard
            </button>
          </div>
        </div>
      </div>
    )
  }
}
