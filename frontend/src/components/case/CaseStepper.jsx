import { STAGE_LABELS, crStatus, reachedStage, stageDone, stageTone } from './workflow.js'

const Tick = () => (
  <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2.5"
       viewBox="0 0 16 16" aria-hidden="true">
    <path d="M3 8l3.5 3.5L13 4" />
  </svg>
)

const Padlock = () => (
  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"
       viewBox="0 0 16 16" aria-hidden="true">
    <rect x="3" y="7" width="10" height="7" rx="1.5" />
    <path d="M5 7V5a3 3 0 0 1 6 0v2" />
  </svg>
)

/**
 * The six-stage progress gate (wireframe_v11 s20, plus CR Status).
 *
 * A locked stage is not merely unstyled — it is unreachable. The gate is what
 * stops a return being signed before the client approved it or filed before it
 * was signed, so it refuses the navigation rather than trusting the button to
 * be hidden.
 *
 * STAGE 6 IS COLOURED BY CR'S ANSWER, not by our progress. Every other
 * medallion says where WE got to; this one says what the register decided, so
 * the verdict is readable off the progress bar without opening the stage. It is
 * the only place data drives the chrome here, and `workflow.stageTone` is the
 * one function that decides it.
 */
export default function CaseStepper({ caseRow, step, onGo, onLocked }) {
  const reached = reachedStage(caseRow)

  return (
    <div className="stepper" role="tablist" aria-label="Case stages">
      {STAGE_LABELS.map((label, i) => {
        const n = i + 1
        const done = stageDone(caseRow, n)
        const unlocked = n <= reached
        const active = n === step
        const tone = stageTone(caseRow, n)

        let cls = 'step'
        if (done) cls += ' done'
        else if (active) cls += ' active'
        else if (unlocked) cls += ' avail'
        else cls += ' locked'
        if (unlocked) cls += ' clickable'
        // AFTER the four above, so its colour wins over `avail`/`active` on a
        // stage whose state is CR's to report. `done` still wins over it —
        // `cr_registered` is the tone AND the tick, and drawing a green
        // medallion without the tick would make the finished case the one
        // state with no tick anywhere.
        if (tone && !done) cls += ` tone-${tone}`

        // Stage 6 states what CR said, not where we are in it. "In progress" on
        // a rejected return would be a screen contradicting its own badge.
        const state = n === 6 && unlocked
          ? crStatus(caseRow).label
          : done ? 'Done'
            : active ? 'In progress'
              : unlocked ? 'Available' : 'Locked'

        return (
          <div
            key={label}
            className={cls}
            role="tab"
            aria-selected={active}
            aria-disabled={!unlocked}
            tabIndex={unlocked ? 0 : -1}
            onClick={() => unlocked
              ? onGo(n)
              : onLocked?.(`Complete "${STAGE_LABELS[reached - 1]}" to unlock ${label}.`)}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                if (unlocked) onGo(n)
                else onLocked?.(`Complete "${STAGE_LABELS[reached - 1]}" to unlock ${label}.`)
              }
            }}
          >
            <div className={`step-line${n > 1 && stageDone(caseRow, n - 1) ? ' filled' : ''}`} />
            <div className="step-num">
              {done ? <Tick /> : !unlocked ? <Padlock /> : n}
            </div>
            <div className="step-lbl">{label}</div>
            <div className="step-state">{state}</div>
          </div>
        )
      })}
    </div>
  )
}
