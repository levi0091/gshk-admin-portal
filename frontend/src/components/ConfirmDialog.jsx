/**
 * A confirmation for an action that is about to change something.
 *
 * `DiscardConfirm` is its sibling but not its replacement: that one is
 * `position: absolute` and sits over the modal it is protecting. This one is a
 * dialog in its own right, for a destructive action taken from a page.
 *
 * Not `window.confirm` — that cannot carry the brand, cannot say WHAT is about
 * to be removed, and cannot be driven from Vitest.
 *
 * The confirm button repeats the verb from the button that opened it, so the
 * action keeps one name the whole way through.
 */
export default function ConfirmDialog({
  title, children, confirmLabel = 'Remove', cancelLabel = 'Cancel',
  busy = false, onConfirm, onCancel,
}) {
  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onCancel() }}>
      <div className="modal modal-sm" role="alertdialog" aria-label={title}>
        <div className="modal-hdr">
          <div className="modal-title">{title}</div>
          <button className="modal-close" onClick={onCancel} aria-label="Close">×</button>
        </div>
        <div className="modal-body confirm-body">{children}</div>
        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? 'Removing…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
