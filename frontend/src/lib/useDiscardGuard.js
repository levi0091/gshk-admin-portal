import { useState } from 'react'

/**
 * Guards a form modal against losing typed input on an accidental dismissal.
 *
 * UAT round 1: a stray click on the backdrop binned everything the operator had
 * keyed. The backdrop no longer closes anything (Levi 2026-10-30), and both ways
 * out — × and Cancel — route through `requestClose()` instead of calling
 * `onClose` directly. A pristine form still closes instantly; a dirty one has to
 * be discarded deliberately.
 */
export default function useDiscardGuard(isDirty, onClose) {
  const [confirming, setConfirming] = useState(false)

  return {
    confirming,
    requestClose: () => (isDirty ? setConfirming(true) : onClose()),
    keepEditing: () => setConfirming(false),
    discard: () => { setConfirming(false); onClose() },
  }
}
