import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.js'
import useAbortableGet from '../lib/useAbortableGet.js'
import { formatDate, formatDateTime } from '../lib/format.js'

/**
 * Soft delete of a company or a natural person (migration 049).
 *
 * A deleted record stays in the database and disappears from every screen:
 * the registries, the pickers and the dashboard stop listing it, and its
 * profile answers "not found" to everybody except a role holding the delete
 * permission, who sees it read-only with a Restore button. The API decides all
 * of that; these three pieces are only what the screens show.
 */

const NOUN = { company: 'company', person: 'person' }

/**
 * The confirmation, and the one place a deletion is asked for.
 *
 * IT ASKS THE SERVER WHAT STANDS IN THE WAY BEFORE IT ASKS FOR A REASON. A
 * record still holding a current role elsewhere, or a company with a case in
 * progress, cannot be deleted (Levi 2026-09-20) -- and finding that out after
 * writing the reason is the wrong order. The list says what to do instead:
 * end the appointment on the company it belongs to, or close the case.
 *
 * THE RECORD IS NAMED BY WHAT IS UNIQUE ABOUT IT. Names are not: Payward
 * Limited has two profiles with the same name AND the same BR number, so the
 * dialog also gives the date each was created -- the one thing that tells the
 * two apart on the screen.
 *
 * No typed-back confirmation, unlike closing a case: a deletion can be undone
 * from the registry's Deleted tab, and a closure cannot.
 */
export function DeleteRecordModal({ kind, basePath, name, identifiers = [], onClose, onDeleted }) {
  const noun = NOUN[kind]
  const [check, setCheck] = useState(null)
  const [checkError, setCheckError] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function runCheck() {
    setCheck(null)
    setCheckError('')
    api.get(`${basePath}/deletion-check`)
      .then(setCheck)
      .catch(e => setCheckError(e.message))
  }

  useEffect(runCheck, [basePath])

  const ready = check?.can_delete && reason.trim() && !busy

  async function submit() {
    if (!ready) return
    setBusy(true)
    setError('')
    try {
      await api.post(`${basePath}/delete`, { reason: reason.trim() })
      await onDeleted()
    } catch (e) {
      setError(e.message)
      setBusy(false)
      // A 409 means something changed since the check -- somebody gave it a
      // role or opened a case -- so the list above the reason is stale.
      if (e.status === 409) runCheck()
    }
  }

  const links = check?.links || []
  const cases = check?.cases || []

  return (
    <div className="overlay" onClick={busy ? undefined : onClose}>
      <div className="modal modal-sm" onClick={e => e.stopPropagation()}
           role="alertdialog" aria-label={`Delete ${noun}`}>
        <div className="modal-hdr">
          <div className="modal-title">Delete this {noun}?</div>
          <div className="modal-close" onClick={busy ? undefined : onClose}
               role="button" aria-label={`Cancel and keep this ${noun}`}>×</div>
        </div>

        <div className="modal-body">
          <div className="delete-subject">
            <div className="delete-subject-name">{name}</div>
            {identifiers.filter(Boolean).map(text => (
              <div key={text} className="delete-subject-id">{text}</div>
            ))}
          </div>

          {error && (
            <div className="alert al-danger" role="alert" style={{ marginBottom: 14 }}>
              <span className="al-icon">⚠</span>
              <div className="al-body"><b>{error}</b></div>
            </div>
          )}

          {!check && !checkError && (
            <div className="f-hint" role="status">Checking whether it can be deleted…</div>
          )}
          {checkError && (
            <div className="alert al-danger" role="alert">
              <span className="al-icon">⚠</span>
              <div className="al-body">
                <b>Could not check this {noun}: {checkError}</b>
              </div>
            </div>
          )}

          {check && !check.can_delete && (
            <div className="alert al-warn" role="status">
              <span className="al-icon">⚠</span>
              <div className="al-body">
                <b>This {noun} cannot be deleted yet.</b>
                {links.length > 0 && (
                  <>
                    <div style={{ marginTop: 6 }}>
                      It still holds a current role at {links.length === 1
                        ? 'this company' : `these ${links.length} companies`}.
                      End each one on the company&rsquo;s own profile first, so
                      nobody&rsquo;s annual return loses an officer or member
                      without anyone looking at it:
                    </div>
                    <ul className="delete-blockers">
                      {links.map(l => (
                        <li key={l.company_id}>
                          <Link to={`/companies/${l.company_id}`}>{l.company_name || 'Unnamed company'}</Link>
                          {l.br_number && <span className="t-muted"> · BRN {l.br_number}</span>}
                          <span className="t-muted"> — {l.roles.join(', ')}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {cases.length > 0 && (
                  <>
                    <div style={{ marginTop: 6 }}>
                      It has {cases.length === 1 ? 'a case' : `${cases.length} cases`} still
                      in progress. Close {cases.length === 1 ? 'it' : 'them'} first,
                      or wait until the Companies Registry has registered the return:
                    </div>
                    <ul className="delete-blockers">
                      {cases.map(k => (
                        <li key={k.case_id}>
                          <Link to={`/cases/${k.case_id}`}>{k.case_no || 'Case'}</Link>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </div>
          )}

          {check?.can_delete && (
            <>
              <div className="alert al-info" role="status" style={{ marginBottom: 16 }}>
                <span className="al-icon">ℹ</span>
                <div className="al-body">
                  It will disappear from every list, search and dropdown, and
                  nothing new can be done with it. The record and its history
                  stay, and it can be restored from the registry&rsquo;s
                  Deleted tab.
                </div>
              </div>
              <div className="f-group">
                <label className="f-label" htmlFor="del-reason">
                  Why is this {noun} being deleted?
                </label>
                <textarea
                  id="del-reason" className="f-input f-textarea" rows={3} autoFocus
                  value={reason} disabled={busy} maxLength={500}
                  placeholder={kind === 'company'
                    ? 'e.g. duplicate of the profile imported from Viewpoint'
                    : 'e.g. created by mistake; the same person is already on file'}
                  onChange={e => setReason(e.target.value)}
                />
                <span className="f-hint">
                  Required. It is shown to whoever restores it, and written to
                  the audit trail.
                </span>
              </div>
            </>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={busy}>
            {check && !check.can_delete ? 'Close' : 'Cancel'}
          </button>
          {check?.can_delete && (
            <button className="btn btn-danger" onClick={submit} disabled={!ready}>
              {busy ? 'Deleting…' : `Delete ${noun}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * What a DELETED record's profile says at the top, to the only people who can
 * open it: who deleted it, when, why -- and the way back.
 */
export function DeletedBanner({ kind, record, basePath, canRestore, onRestored }) {
  const noun = NOUN[kind]
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function restore() {
    setBusy(true)
    setError('')
    try {
      await api.post(`${basePath}/restore`, {})
      await onRestored()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="alert al-danger deleted-banner" role="status">
      <span className="al-icon">🗑</span>
      <div className="al-body">
        <b>This {noun} has been deleted.</b>
        <div style={{ marginTop: 4 }}>
          Deleted {formatDateTime(record.deleted_at)}
          {record.deleted_by_name ? ` by ${record.deleted_by_name}` : ''}.
          {record.deleted_reason && <> Reason: <i>{record.deleted_reason}</i></>}
        </div>
        <div style={{ marginTop: 4 }}>
          Nobody else can see it, and it cannot be changed until it is restored.
        </div>
        {error && <div style={{ marginTop: 6 }}><b>{error}</b></div>}
      </div>
      {canRestore && (
        <button className="btn btn-primary btn-sm" onClick={restore} disabled={busy}>
          {busy ? 'Restoring…' : `Restore ${noun}`}
        </button>
      )}
    </div>
  )
}

/**
 * A profile the API would not show: never existed, or deleted and the viewer
 * may not see deleted records. The API answers the two identically on purpose,
 * so this does too -- and gives the way out that the bare error box did not.
 */
export function RecordGone({ kind, backTo, backLabel }) {
  return (
    <div className="card record-gone">
      <div className="card-title">This {NOUN[kind]} is not available</div>
      <div className="pg-sub" style={{ margin: '8px 0 16px' }}>
        It does not exist, or it has been deleted.
      </div>
      <Link className="btn btn-outline" to={backTo}>{backLabel}</Link>
    </div>
  )
}

const DELETED_PAGE_SIZE = 50

/**
 * A registry's Deleted tab: the ONE list a deleted record still appears in,
 * shown only to a role holding the delete level (the API refuses anyone else),
 * because it exists to restore from. Most recently deleted first.
 *
 * Its own table rather than the registry's: the registry's columns and
 * filters are about live records -- status, anniversary, role -- and none of
 * them means anything here. What matters is who deleted it, when and why.
 */
export function DeletedTable({ endpoint, rowsKey, search, refLabel, refOf, onOpen }) {
  const [page, setPage] = useState(1)
  useEffect(() => { setPage(1) }, [search])

  const params = new URLSearchParams({
    page: String(page), page_size: String(DELETED_PAGE_SIZE),
  })
  if (search) params.set('search', search)
  const { data, loading, error } = useAbortableGet(`${endpoint}?${params}`)

  const rows = data?.[rowsKey] || []
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / DELETED_PAGE_SIZE))

  if (error) {
    return (
      <div className="alert al-danger" role="alert">
        <span className="al-icon">⚠</span>
        <div className="al-body"><b>Could not load deleted records: {error}</b></div>
      </div>
    )
  }

  return (
    <>
      <div className="tbl-wrap tbl-stack">
        <table aria-label="Deleted records">
          <thead>
            <tr>
              <th>Name</th>
              <th>{refLabel}</th>
              <th>Deleted</th>
              <th>By</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="empty-state">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={5} className="empty-state">
                {search ? 'Nothing deleted matches that search.' : 'Nothing has been deleted.'}
              </td></tr>
            ) : rows.map(r => (
              <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
                <td data-label="Name">
                  <span className="td-primary">{r.company_name || r.full_name}</span>
                </td>
                <td data-label={refLabel}><span className="td-muted">{refOf(r) || '—'}</span></td>
                <td data-label="Deleted"><span className="td-muted">{formatDateTime(r.deleted_at)}</span></td>
                <td data-label="By"><span className="td-muted">{r.deleted_by_name || '—'}</span></td>
                <td data-label="Reason">{r.deleted_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!loading && total > 0 && (
        <div className="pager">
          <span>
            {(page - 1) * DELETED_PAGE_SIZE + 1}–{Math.min(page * DELETED_PAGE_SIZE, total)} of {total}
          </span>
          <div className="pager-btns">
            <button className="btn btn-outline btn-sm" disabled={page <= 1}
                    onClick={() => setPage(p => p - 1)}>Previous</button>
            <button className="btn btn-outline btn-sm" disabled={page >= lastPage}
                    onClick={() => setPage(p => p + 1)}>Next</button>
          </div>
        </div>
      )}
    </>
  )
}

/** Created-on, for telling two same-named records apart. */
export function createdOn(record) {
  return record?.created_at ? `Created ${formatDate(record.created_at)}` : null
}
