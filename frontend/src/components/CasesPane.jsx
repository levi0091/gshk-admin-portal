import { useState } from 'react'

import { WorkflowBadge } from './CaseStatusBadge.jsx'
import StatusBadge from './StatusBadge.jsx'
import { CR_TONE, STAGE_LABELS } from './case/workflow.js'
import { formatDate, formatDateTime } from '../lib/format.js'

/**
 * The company profile's Cases pane (wireframe_v11 s3: "completed collapse, live
 * expands").
 *
 * WHAT AN OPERATOR COMES HERE TO LEARN, in the order the card answers it:
 * which return each case files (the year), where it has got to (the badge and
 * the stage bar), and whether anybody has touched it lately (created / updated).
 * Everything else is one click away on the case itself.
 *
 * THE YEAR LEADS because it is what a case IS: one live case per company per
 * return year (migration 047), so four missed years read as four rows headed
 * 2023, 2024, 2025, 2026. The case number is an id; its year is the year the
 * case was OPENED, which for a backlog return is not the year it files — so it
 * sits under the title, never in the year's place.
 */

//: Where OUR five-stage part of the workflow puts each code, and the colour of
//: that stage: `act` is ours to do, `info` is waiting on somebody else, `bad` is
//: a refusal. Same semantics as the dashboard badges. Anything with CR (stage 6)
//: takes its tone from `workflow.CR_TONE`, the one table that decides what CR's
//: answer looks like on the stepper — this bar must not have a second opinion.
const OUR_STAGE = {
  client_verification: [1, 'act'],
  awaiting_client: [1, 'info'],
  client_rejected: [1, 'bad'],
  data_verification: [2, 'act'],
  signing: [3, 'act'],
  submission: [4, 'act'],
}

//: Codes after which nothing more will happen on the case. These collapse.
//: `client_rejected` is NOT one: the client said no, and somebody now has to
//: fix the data and restart verification — hiding it would hide the work.
//: `cr_pending` / `cr_approved` / `cr_not_checked` are not either: the return is
//: still on its way to the register.
const NAR1_ENDED = new Set(['cr_registered', 'cr_rejected', 'closed'])
const NNC1_ENDED = new Set(['approved', 'rejected'])

/** `{stage, tone}` on the six-stage bar, or null for a code with no position. */
export function stageOf(code) {
  if (OUR_STAGE[code]) return { stage: OUR_STAGE[code][0], tone: OUR_STAGE[code][1] }
  if (code in CR_TONE) return { stage: STAGE_LABELS.length, tone: CR_TONE[code] }
  return null
}

function codeOf(status) {
  if (!status) return null
  return typeof status === 'string' ? status : status.code || null
}

/** One shape for both case tables, so the card does not branch on its source. */
function normalise(c, kind) {
  if (kind === 'nar1') {
    const code = codeOf(c.workflow_status)
    return {
      id: c.id, kind, code, status: c.workflow_status,
      // Resolved by the API (a legacy case stores no year but was filed for
      // one); the stored column is the fallback for an older payload.
      year: c.return_year ?? c.ar_period_year ?? null,
      caseNo: c.case_no,
      createdAt: c.created_at, createdBy: c.created_by_name,
      updatedAt: c.updated_at,
      closedAt: c.closed_at, closedBy: c.closed_by_name, closedReason: c.closed_reason,
      ended: NAR1_ENDED.has(code),
    }
  }
  return {
    id: c.id, kind, code: c.status, status: c.status, year: null,
    caseNo: null, createdAt: c.created_at, createdBy: null, updatedAt: c.updated_at,
    ended: NNC1_ENDED.has(c.status),
  }
}

/** Every case, in-progress first; within each, newest return year first. */
export function orderedCases(cases) {
  const rows = [
    ...(cases?.nar1 || []).map(c => normalise(c, 'nar1')),
    ...(cases?.nnc1 || []).map(c => normalise(c, 'nnc1')),
  ]
  // A case with no year yet is the newest thing on the company, so it heads
  // its group rather than trailing the dated ones.
  const yearKey = r => (r.year == null ? Infinity : Number(r.year))
  return rows.sort((a, b) =>
    (a.ended - b.ended)
    || (yearKey(b) - yearKey(a))
    || String(b.createdAt || '').localeCompare(String(a.createdAt || '')))
}

/** "2 in progress · 1 finished" — the Cases card's subtitle. */
export function caseSummary(cases) {
  const rows = orderedCases(cases)
  if (rows.length === 0) return null
  const ended = rows.filter(r => r.ended).length
  const live = rows.length - ended
  return [live && `${live} in progress`, ended && `${ended} finished`]
    .filter(Boolean).join(' · ')
}

export default function CasesPane({ cases, onOpen }) {
  // Only what the reader has CHANGED is stored; everything else follows the
  // rule. A refetch after an edit then keeps what they opened or closed, and a
  // case that has just been filed and registered folds itself away.
  const [toggled, setToggled] = useState({})
  const rows = orderedCases(cases)

  if (rows.length === 0) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No cases yet.</div>
  }

  const live = rows.filter(r => !r.ended)
  const ended = rows.filter(r => r.ended)
  const grouped = live.length > 0 && ended.length > 0
  const card = r => (
    <CaseCard key={`${r.kind}-${r.id}`} row={r} onOpen={onOpen}
              open={toggled[r.id] ?? !r.ended}
              onToggle={() => setToggled(t => ({ ...t, [r.id]: !(t[r.id] ?? !r.ended) }))} />
  )

  return (
    <div className="cases">
      {grouped && <div className="cases-group">In progress</div>}
      {live.map(card)}
      {grouped && <div className="cases-group">Finished</div>}
      {ended.map(card)}
    </div>
  )
}

function CaseCard({ row, open, onToggle, onOpen }) {
  const bodyId = `case-body-${row.id}`
  const nar1 = row.kind === 'nar1'
  const position = nar1 ? stageOf(row.code) : null

  return (
    <article className={`case-card${row.ended ? ' ended' : ''}${open ? ' open' : ''}`}>
      <button type="button" className="case-card-hdr" aria-expanded={open}
              aria-controls={bodyId} onClick={onToggle}>
        <span className="case-year">
          {!nar1 ? <span className="case-year-code">NNC1</span>
            : row.year ? (
              <><span className="visually-hidden">Return year </span>{row.year}</>
            ) : (
              // The year is mandatory before anything is sent, and there is no
              // default (2026-09-19) — so its absence is a fact to show, not a
              // blank to leave.
              <span className="case-year-none">Year<br />not set</span>
            )}
        </span>
        <span className="case-card-titles">
          <span className="case-card-title">{nar1 ? 'Annual Return' : 'Incorporation'}</span>
          <span className="case-card-no">
            {row.caseNo || `Case ${String(row.id).slice(0, 8)}`}
          </span>
        </span>
        <span className="case-card-status">
          {nar1 ? <WorkflowBadge status={row.status} /> : <StatusBadge status={row.status} />}
        </span>
        <svg className="case-card-chev" width="12" height="12" viewBox="0 0 12 12"
             aria-hidden="true">
          <path d="M4.5 2.5 8 6l-3.5 3.5" fill="none" stroke="currentColor"
                strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="case-card-body" id={bodyId}>
          {/* The one action sits on the first line, beside the bar, so it is in
              the same place on every card. Beside the dates it wrapped onto a
              line of its own whenever a name or "Sept" made them wider. */}
          <div className="case-card-lead">
            {position ? <StageBar {...position} /> : <span />}
            {onOpen && (
              <button type="button" className="case-open" onClick={() => onOpen(row.id)}>
                Open case <span aria-hidden="true">→</span>
              </button>
            )}
          </div>
          <dl className="case-facts">
              <dt>Created</dt>
              <dd>
                {formatDate(row.createdAt)}
                {row.createdBy && <span className="case-by"> · {row.createdBy}</span>}
              </dd>
              <dt>Updated</dt>
              <dd>{formatDateTime(row.updatedAt)}</dd>
              {row.closedAt && (
                <>
                  <dt>Closed</dt>
                  <dd>
                    {formatDate(row.closedAt)}
                    {row.closedBy && <span className="case-by"> · {row.closedBy}</span>}
                  </dd>
                  {row.closedReason && <dd className="case-reason">{row.closedReason}</dd>}
                </>
              )}
          </dl>
        </div>
      )}
    </article>
  )
}

/**
 * The six stages as one thin bar — the case screen's stepper, at a size that
 * fits a dozen cases down a side pane. Done stages are green; the current one
 * wears its tone; the rest are empty. `cr_registered` is the one state where
 * the last stage is done rather than current.
 *
 * No printed "Stage 3 of 6": the badge beside the year already says where the
 * case is, in words. The count is the bar's label and its tooltip.
 */
function StageBar({ stage, tone }) {
  const total = STAGE_LABELS.length
  const finished = tone === 'ok' && stage === total
  const summary = `Stage ${stage} of ${total}: ${STAGE_LABELS[stage - 1]}`

  return (
    <div className="case-stage-bar" role="img" aria-label={summary} title={summary}>
      {STAGE_LABELS.map((label, i) => {
        const n = i + 1
        const state = n < stage || finished ? 'done' : n === stage ? `now tone-${tone}` : 'todo'
        return <span key={label} className={`case-stage ${state}`} />
      })}
    </div>
  )
}
