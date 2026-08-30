/**
 * The "are you sure?" shown over a dirty modal that someone tried to dismiss.
 *
 * Deliberately not `window.confirm` — that can't carry the brand and can't be
 * driven from Vitest. Pair it with `useDiscardGuard`.
 */
export default function DiscardConfirm({ onKeepEditing, onDiscard }) {
  return (
    <div className="modal-confirm" role="alertdialog" aria-label="Discard changes">
      <div className="modal-confirm-card">
        <div className="modal-confirm-title">Discard changes?</div>
        <div className="modal-confirm-text">Your entries will be lost.</div>
        <div className="modal-confirm-actions">
          <button className="btn btn-outline" onClick={onKeepEditing}>Keep editing</button>
          <button className="btn btn-danger" onClick={onDiscard}>Discard</button>
        </div>
      </div>
    </div>
  )
}
