import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { formatDate, formatDateTime } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'
import {
  DEFAULT_LIMITS, extensionOf, groupByBucket, refusalFor,
} from '../lib/documentSections.js'
import { fetchRemote, looksLikeFileDrag, readDrop } from '../lib/dropFiles.js'
import ConfirmDialog from './ConfirmDialog.jsx'

/**
 * A profile's documents as BUCKETS (GSHK 2026-11-21).
 *
 * What GSHK asked for, and where each lives below:
 *  - No document types, no per-file form: drop files into a bucket, many at a
 *    time (`startUpload`), from anywhere — the whole page becomes a drop
 *    target the moment a file is dragged over it (`DropOverlay`).
 *  - At most `max_files` (20) per drop: a bigger drop is refused whole, by
 *    count, before anything is sent.
 *  - Almost any file type: only what EXECUTES is refused (served by the API).
 *  - Tag and describe in bulk "with no need to click in": the files a drop
 *    just uploaded come back SELECTED, so the bulk bar is already open on
 *    them; every row also edits in place.
 *  - Sorted by upload date, which is shown quietly at the end of the row.
 *  - No Document History: the audit trail already records every upload, move,
 *    tag and removal.
 *
 * AUTOSAVE, deliberately. A description or tag saves when the field is left
 * (or Enter is pressed); a bulk action applies when its button is pressed.
 * None of it is a filing, every change is audited, and every change is undone
 * by making it again — the cost of an explicit Save here is one more click per
 * file, which is exactly what GSHK said they do not have time for.
 *
 * VIEW: details list, shown straight away. File names and descriptions are
 * what an operator scans for, which thumbnails cannot carry; each bucket shows
 * its newest PREVIEW rows and expands in place, so a bucket of 80 slips does
 * not push the rest of the profile off the screen.
 */

const PREVIEW = 5
const CONCURRENCY = 3

let seq = 0
const nextKey = () => `u${++seq}`

export default function DocumentBuckets({
  ownerKind, ownerId, ownerName, documents, buckets, limits = DEFAULT_LIMITS,
  canEdit = false, canRemove = false, canDownload = false,
}) {
  const basePath = ownerKind === 'person'
    ? `/persons/${ownerId}/documents`
    : `/companies/${ownerId}/documents`

  const [docs, setDocs] = useState(() => documents || [])
  useEffect(() => { setDocs(documents || []) }, [documents])

  const [selected, setSelected] = useState(() => new Set())
  const [fresh, setFresh] = useState(() => new Set())
  const [expanded, setExpanded] = useState(() => new Set())
  const [batch, setBatch] = useState(null)
  const [notice, setNotice] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const anchor = useRef(null)

  const grouped = useMemo(() => groupByBucket(docs, buckets), [docs, buckets])
  const targets = (buckets || []).filter(b => !b.fallback)
  const shown = (buckets || []).filter(b => !b.fallback || grouped[b.key]?.length)
  const byId = useMemo(() => new Map(docs.map(d => [d.id, d])), [docs])
  const canSelect = canEdit || canRemove || canDownload

  // ── edits ────────────────────────────────────────────────────────────────

  const merge = useCallback(rows => {
    const next = new Map((Array.isArray(rows) ? rows : []).map(r => [r.id, r]))
    setDocs(list => list.map(d => (next.has(d.id) ? { ...d, ...next.get(d.id) } : d)))
  }, [])

  const edit = useCallback(async (ids, change) => {
    const rows = await api.patch(basePath, { ids: [...ids], ...change })
    merge(rows)
    return rows
  }, [basePath, merge])

  async function bulk(change, done) {
    setBusy(true)
    setNotice(null)
    try {
      await edit(selected, change)
      setNotice({ tone: 'ok', text: done })
    } catch (err) {
      setNotice({ tone: 'danger', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  async function removeConfirmed() {
    const ids = confirm.ids
    setBusy(true)
    const failed = []
    const gone = new Set()
    for (const id of ids) {
      try {
        await api.del(`/documents/${id}`)
        gone.add(id)
      } catch (err) {
        failed.push(`${byId.get(id)?.file_name || 'A document'}: ${err.message}`)
      }
    }
    setDocs(list => list.filter(d => !gone.has(d.id)))
    setSelected(s => new Set([...s].filter(id => !gone.has(id))))
    setConfirm(null)
    setBusy(false)
    if (failed.length) setNotice({ tone: 'danger', text: failed.join(' · ') })
  }

  // ── selection ────────────────────────────────────────────────────────────

  function toggle(id, withShift, bucketDocs) {
    // Read the anchor NOW: the updater below runs later, after it has moved.
    const from = anchor.current
    setFresh(new Set())
    setSelected(prev => {
      const next = new Set(prev)
      const on = !prev.has(id)
      if (withShift && from && bucketDocs) {
        const ids = bucketDocs.map(d => d.id)
        const a = ids.indexOf(from)
        const b = ids.indexOf(id)
        if (a >= 0 && b >= 0) {
          for (const x of ids.slice(Math.min(a, b), Math.max(a, b) + 1)) {
            if (on) next.add(x); else next.delete(x)
          }
          return next
        }
      }
      if (on) next.add(id); else next.delete(id)
      return next
    })
    anchor.current = id
  }

  function toggleBucket(bucketDocs) {
    setFresh(new Set())
    setSelected(prev => {
      const all = bucketDocs.every(d => prev.has(d.id))
      const next = new Set(prev)
      for (const d of bucketDocs) { if (all) next.delete(d.id); else next.add(d.id) }
      return next
    })
  }

  // ── upload ───────────────────────────────────────────────────────────────

  const startUpload = useCallback(async (fileList, bucketKey) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    const bucket = (buckets || []).find(b => b.key === bucketKey)
    if (files.length > limits.max_files) {
      setNotice({
        tone: 'danger',
        text: `That was ${files.length} files. Up to ${limits.max_files} can be uploaded `
          + 'at a time, so nothing was uploaded. Drop them in smaller batches.',
      })
      return
    }
    setNotice(null)
    const items = files.map(file => {
      const error = refusalFor(file, limits)
      return { key: nextKey(), name: file.name, file, status: error ? 'failed' : 'queued', error }
    })
    setBatch({ bucket: bucket?.label || bucketKey, items })
    const update = (key, patch) => setBatch(b => (b && {
      ...b, items: b.items.map(i => (i.key === key ? { ...i, ...patch } : i)),
    }))

    const queue = items.filter(i => i.status === 'queued')
    const created = []
    async function worker() {
      while (queue.length) {
        const item = queue.shift()
        update(item.key, { status: 'uploading' })
        const fd = new FormData()
        fd.append('file', item.file)
        fd.append('bucket', bucketKey)
        try {
          const doc = await api.upload(basePath, fd)
          created.push(doc)
          setDocs(list => [{ tags: [], ...doc }, ...list])
          update(item.key, { status: 'done', file: null })
        } catch (err) {
          update(item.key, { status: 'failed', error: err.message, file: null })
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker))
    if (created.length) {
      const ids = new Set(created.map(d => d.id))
      setSelected(ids)
      setFresh(ids)
    }
  }, [basePath, buckets, limits])

  async function takeDrop(dt, bucketKey) {
    const { files, remote } = readDrop(dt)
    if (files.length) return startUpload(files, bucketKey)
    if (remote) {
      try {
        return startUpload([await fetchRemote(remote)], bucketKey)
      } catch (err) {
        return setNotice({ tone: 'danger', text: err.message })
      }
    }
    return setNotice({ tone: 'danger', text: 'There was no file in that drop.' })
  }

  const overlay = useWindowFileDrag(canEdit && targets.length > 0)

  // ── render ───────────────────────────────────────────────────────────────

  const selectedDocs = [...selected].map(id => byId.get(id)).filter(Boolean)
  const suggestionsFor = keys => [...new Set((buckets || [])
    .filter(b => keys.includes(b.key)).flatMap(b => b.suggestions || []))]

  return (
    <div className={`card mb-16 bk-card${selected.size ? ' has-bulk' : ''}`}>
      <div className="card-hdr">
        <div>
          <div className="card-title">
            Documents <span className="count-pill">{docs.filter(d => d.bucket).length}</span>
          </div>
          <div className="card-sub">
            {canEdit
              ? `Drag files anywhere onto this page to upload, up to ${limits.max_files} at a time`
              : 'Newest upload first in each bucket'}
          </div>
        </div>
      </div>

      {notice && (
        <div className={`alert ${notice.tone === 'danger' ? 'al-danger' : 'al-success'} bk-notice`}
             role={notice.tone === 'danger' ? 'alert' : 'status'}>
          <div className="al-body">{notice.text}</div>
          <button type="button" className="bk-link" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}

      {batch && <UploadTray batch={batch} onDismiss={() => setBatch(null)} />}

      {shown.map(bucket => (
        <Bucket
          key={bucket.key}
          bucket={bucket}
          docs={grouped[bucket.key] || []}
          expanded={expanded.has(bucket.key)}
          onExpand={on => setExpanded(prev => {
            const next = new Set(prev)
            if (on) next.add(bucket.key); else next.delete(bucket.key)
            return next
          })}
          selected={selected}
          fresh={fresh}
          canSelect={canSelect}
          canEdit={canEdit}
          canRemove={canRemove}
          canDownload={canDownload}
          limits={limits}
          onToggle={toggle}
          onToggleAll={toggleBucket}
          onPick={files => startUpload(files, bucket.key)}
          onEdit={edit}
          onRemove={doc => setConfirm({ ids: [doc.id] })}
          onError={text => setNotice({ tone: 'danger', text })}
        />
      ))}

      {selectedDocs.length > 0 && (
        <BulkBar
          docs={selectedDocs}
          isFresh={selectedDocs.length === fresh.size && selectedDocs.every(d => fresh.has(d.id))}
          targets={targets}
          suggestions={suggestionsFor(selectedDocs.map(d => d.bucket))}
          limits={limits}
          busy={busy}
          canEdit={canEdit}
          canRemove={canRemove}
          canDownload={canDownload}
          onClear={() => { setSelected(new Set()); setFresh(new Set()) }}
          onTag={tag => bulk({ add_tags: [tag] }, `Tagged ${selectedDocs.length} “${tag}”.`)}
          onDescribe={text => bulk({ title: text },
            text ? `Description set on ${selectedDocs.length}.` : `Description cleared on ${selectedDocs.length}.`)}
          onMove={key => bulk({ bucket: key },
            `Moved ${selectedDocs.length} to ${targets.find(t => t.key === key)?.label}.`)}
          onDownload={() => selectedDocs.forEach(d => downloadDocument(d.id))}
          onRemove={() => setConfirm({ ids: selectedDocs.map(d => d.id) })}
        />
      )}

      {overlay.active && (
        <DropOverlay
          ownerName={ownerName}
          targets={targets}
          max={limits.max_files}
          counts={grouped}
          onDrop={(dt, key) => { overlay.close(); takeDrop(dt, key) }}
          onCancel={overlay.close}
        />
      )}

      {confirm && (
        <ConfirmDialog
          title={confirm.ids.length === 1 ? 'Remove document' : `Remove ${confirm.ids.length} documents`}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={removeConfirmed}
        >
          <RemoveDocumentsBody docs={confirm.ids.map(id => byId.get(id)).filter(Boolean)}
                               ownerName={ownerName} />
        </ConfirmDialog>
      )}
    </div>
  )
}

/**
 * The page-wide drop target. Appears the moment a FILE (not selected text, not
 * a link inside the portal) is dragged over the window, and only when no modal
 * is open — a modal's own drop zone must keep its drop.
 */
function useWindowFileDrag(enabled) {
  const [active, setActive] = useState(false)
  const depth = useRef(0)
  useEffect(() => {
    if (!enabled) return undefined
    const enter = e => {
      if (!looksLikeFileDrag(e.dataTransfer)) return
      if (document.querySelector('.overlay')) return
      depth.current += 1
      setActive(true)
    }
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setActive(false)
    }
    const over = e => { if (looksLikeFileDrag(e.dataTransfer)) e.preventDefault() }
    const drop = e => {
      // A drop that missed every bucket must not make the browser open the
      // file in place of the portal.
      if (looksLikeFileDrag(e.dataTransfer)) e.preventDefault()
      depth.current = 0
      setActive(false)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [enabled])
  useEffect(() => {
    if (!active) return undefined
    const esc = e => { if (e.key === 'Escape') { depth.current = 0; setActive(false) } }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [active])
  return { active, close: () => { depth.current = 0; setActive(false) } }
}

function DropOverlay({ ownerName, targets, max, counts, onDrop }) {
  const [over, setOver] = useState(null)
  return (
    <div className="bk-overlay" role="dialog" aria-label="Drop files into a bucket">
      <div className="bk-overlay-panel">
        <div className="bk-overlay-title">Drop into a bucket</div>
        <div className="bk-overlay-sub">
          {ownerName ? <>Uploading to <b>{ownerName}</b> · </> : null}
          up to {max} files · Esc to cancel
        </div>
        <div className={`bk-targets bk-targets-${Math.min(targets.length, 3)}`}>
          {targets.map(t => (
            <div
              key={t.key}
              className={`bk-target ${over === t.key ? 'is-over' : ''}`}
              data-testid={`drop-${t.key}`}
              onDragEnter={e => { e.preventDefault(); setOver(t.key) }}
              onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }}
              onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(null) }}
              onDrop={e => { e.preventDefault(); e.stopPropagation(); onDrop(e.dataTransfer, t.key) }}
            >
              <IconUpload />
              <span className="bk-target-label">{t.label}</span>
              <span className="bk-target-count">
                {(counts[t.key] || []).length} on file
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function UploadTray({ batch, onDismiss }) {
  const done = batch.items.filter(i => i.status === 'done').length
  const failed = batch.items.filter(i => i.status === 'failed')
  const running = batch.items.some(i => i.status === 'queued' || i.status === 'uploading')
  return (
    <div className="bk-tray" aria-live="polite">
      <div className="bk-tray-hdr">
        <span>
          {running
            ? `Uploading to ${batch.bucket}… ${done} of ${batch.items.length}`
            : `${done} uploaded to ${batch.bucket}`
              + (failed.length ? ` · ${failed.length} not uploaded` : '')}
        </span>
        {!running && (
          <button type="button" className="bk-link" onClick={onDismiss}>Dismiss</button>
        )}
      </div>
      {(running || failed.length > 0) && (
        <ul className="bk-tray-list">
          {batch.items.filter(i => running || i.status === 'failed').map(i => (
            <li key={i.key} className={`bk-tray-item is-${i.status}`}>
              <span className="bk-tray-name">{i.name}</span>
              <span className="bk-tray-state">
                {i.status === 'failed' ? i.error
                  : i.status === 'done' ? 'Uploaded'
                    : i.status === 'uploading' ? 'Uploading…' : 'Waiting'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Bucket({
  bucket, docs, expanded, onExpand, selected, fresh, canSelect, canEdit,
  canRemove, canDownload, limits, onToggle, onToggleAll, onPick, onEdit,
  onRemove, onError,
}) {
  const picker = useRef(null)
  const visible = expanded ? docs : docs.slice(0, PREVIEW)
  const allOn = docs.length > 0 && docs.every(d => selected.has(d.id))
  const someOn = docs.some(d => selected.has(d.id))
  const headId = `bk-h-${bucket.key}`
  return (
    <section className={`bk ${bucket.fallback ? 'bk-fallback' : ''}`} aria-labelledby={headId}>
      <div className="bk-hdr">
        {canSelect && (docs.length > 0 ? (
          <Check checked={allOn} indeterminate={someOn && !allOn}
                 label={`Select all in ${bucket.label}`}
                 onChange={() => onToggleAll(docs)} />
        ) : <span className="bk-check-gap" aria-hidden="true" />)}
        <div className="bk-hdr-text">
          <h3 id={headId} className="bk-title">
            {bucket.label} <span className="bk-count">{docs.length}</span>
          </h3>
          <div className="bk-sub">{bucket.description}</div>
        </div>
        {canEdit && !bucket.fallback && (
          <>
            <input ref={picker} type="file" multiple hidden aria-label={`Choose files for ${bucket.label}`}
                   onChange={e => { onPick(e.target.files); e.target.value = '' }} />
            <button type="button" className="btn btn-outline btn-sm bk-up"
                    onClick={() => picker.current?.click()}>
              <IconUpload /> Upload
            </button>
          </>
        )}
      </div>

      {docs.length === 0 ? (
        canEdit && !bucket.fallback ? (
          <button type="button" className="bk-empty" onClick={() => picker.current?.click()}>
            Nothing here yet. Drag files onto the page, or <span className="bk-browse">browse</span>
          </button>
        ) : (
          <div className="bk-empty bk-empty-ro">Nothing here yet.</div>
        )
      ) : (
        <div className="bk-rows" role="list">
          {visible.map(doc => (
            <DocRow
              key={doc.id}
              doc={doc}
              suggestions={bucket.suggestions || []}
              selected={selected.has(doc.id)}
              fresh={fresh.has(doc.id)}
              canSelect={canSelect}
              canEdit={canEdit}
              canRemove={canRemove}
              canDownload={canDownload}
              limits={limits}
              onToggle={shift => onToggle(doc.id, shift, docs)}
              onEdit={change => onEdit([doc.id], change)}
              onRemove={() => onRemove(doc)}
              onError={onError}
            />
          ))}
        </div>
      )}
      {docs.length > PREVIEW && (
        <button type="button" className="bk-more" onClick={() => onExpand(!expanded)}>
          {expanded ? 'Show fewer' : `Show all ${docs.length}`}
        </button>
      )}
    </section>
  )
}

const KIND = [
  [['pdf'], 'pdf'],
  [['doc', 'docx', 'rtf', 'odt', 'pages'], 'doc'],
  [['xls', 'xlsx', 'xlsm', 'csv', 'ods', 'numbers'], 'sheet'],
  [['ppt', 'pptx', 'odp', 'key'], 'slide'],
  [['jpg', 'jpeg', 'png', 'gif', 'heic', 'heif', 'tif', 'tiff', 'bmp', 'webp', 'svg'], 'image'],
  [['msg', 'eml'], 'mail'],
  [['txt', 'html', 'htm', 'md', 'xml', 'json'], 'text'],
]

function kindOf(name) {
  const ext = extensionOf(name)
  return KIND.find(([exts]) => exts.includes(ext))?.[1] || 'other'
}

function DocRow({
  doc, suggestions, selected, fresh, canSelect, canEdit, canRemove,
  canDownload, limits, onToggle, onEdit, onRemove, onError,
}) {
  const [draft, setDraft] = useState(doc.title || '')
  const [state, setState] = useState('')
  const [adding, setAdding] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  useEffect(() => { setDraft(doc.title || '') }, [doc.title])

  const tags = doc.tags || []
  const ext = extensionOf(doc.file_name)
  const versions = [...(doc.document_versions || [])]
    .sort((a, b) => b.version_number - a.version_number)
  const earlier = versions.filter(v => v.version_number !== doc.current_version)

  async function save(change) {
    setState('saving')
    try {
      await onEdit(change)
      setState('saved')
      setTimeout(() => setState(s => (s === 'saved' ? '' : s)), 1600)
    } catch (err) {
      setState('')
      onError(`${doc.file_name}: ${err.message}`)
      return false
    }
    return true
  }

  async function commitDescription() {
    const next = draft.trim()
    if (next === (doc.title || '')) return
    if (!(await save({ title: next }))) setDraft(doc.title || '')
  }

  return (
    <div role="listitem"
         className={`bk-row ${selected ? 'is-sel' : ''} ${fresh ? 'is-fresh' : ''}`}>
      {canSelect && (
        <Check checked={selected} label={`Select ${doc.file_name}`}
               onChange={(_e, shift) => onToggle(shift)} />
      )}
      <span className={`bk-ext bk-ext-${kindOf(doc.file_name)}`} aria-hidden="true">
        {(ext || 'file').slice(0, 4)}
      </span>
      <div className="bk-main">
        {canDownload ? (
          <button type="button" className="bk-name" title="Download"
                  onClick={() => downloadDocument(doc.id)}>
            {doc.file_name || 'Untitled'}
          </button>
        ) : <span className="bk-name bk-name-ro">{doc.file_name || 'Untitled'}</span>}
        {/* Line two: tags, then the description, editable in place. The
            file name keeps the whole first line, whatever the tags are. */}
        {(canEdit || tags.length > 0 || doc.title) && (
          <div className="bk-line2">
            {tags.map(t => (
              <span key={t} className="bk-tag">
                {t}
                {canEdit && (
                  <button type="button" aria-label={`Remove tag ${t}`}
                          onClick={() => save({ remove_tags: [t] })}><IconX /></button>
                )}
              </span>
            ))}
            {canEdit && tags.length < limits.max_tags && (adding ? (
              <TagInput
                suggestions={suggestions.filter(s => !tags.includes(s))}
                maxLength={limits.max_tag_length}
                label={`Add a tag to ${doc.file_name}`}
                onAdd={t => save({ add_tags: [t] })}
                onClose={() => setAdding(false)}
              />
            ) : (
              <button type="button" className="bk-addtag" onClick={() => setAdding(true)}
                      aria-label={`Add a tag to ${doc.file_name}`}>
                <IconPlus /> Tag
              </button>
            ))}
            {canEdit ? (
              <input
                className="bk-desc"
                value={draft}
                maxLength={limits.max_description_length}
                placeholder="Add a description"
                aria-label={`Description of ${doc.file_name}`}
                onChange={e => setDraft(e.target.value)}
                onBlur={commitDescription}
                onKeyDown={e => {
                  if (e.key === 'Enter') e.currentTarget.blur()
                  if (e.key === 'Escape') { setDraft(doc.title || ''); setTimeout(() => e.target.blur()) }
                }}
              />
            ) : (doc.title && <div className="bk-desc-ro">{doc.title}</div>)}
          </div>
        )}
        {showVersions && earlier.length > 0 && (
          <div className="bk-versions">
            {earlier.map(v => (
              <button type="button" key={v.id || v.version_number} className="bk-link"
                      onClick={() => downloadDocument(doc.id, v.version_number)}>
                v{v.version_number} · {formatDate(v.created_at)}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="bk-meta">
        {state === 'saving' && <span className="bk-state">Saving…</span>}
        {state === 'saved' && <span className="bk-state bk-state-ok">Saved</span>}
        {earlier.length > 0 && (
          <button type="button" className="bk-ver" onClick={() => setShowVersions(v => !v)}
                  aria-expanded={showVersions}
                  title={`${earlier.length} earlier version${earlier.length === 1 ? '' : 's'}`}>
            v{doc.current_version}
          </button>
        )}
        <time className="bk-date" dateTime={doc.uploaded_at || doc.created_at}
              title={`Uploaded ${formatDateTime(doc.uploaded_at || doc.created_at)}`}>
          {formatDate(doc.uploaded_at || doc.created_at)}
        </time>
      </div>

      <div className="bk-actions">
        {canDownload && (
          <button type="button" className="bk-icon" aria-label={`Download ${doc.file_name}`}
                  title="Download" onClick={() => downloadDocument(doc.id)}><IconDownload /></button>
        )}
        {canRemove && (
          <button type="button" className="bk-icon bk-icon-danger" aria-label={`Remove ${doc.file_name}`}
                  title="Remove" onClick={onRemove}><IconTrash /></button>
        )}
      </div>
    </div>
  )
}

let listSeq = 0

function TagInput({ suggestions, maxLength, label, onAdd, onClose, autoFocus = true }) {
  const [value, setValue] = useState('')
  const [listId] = useState(() => `bk-tags-${++listSeq}`)
  function commit() {
    const v = value.trim()
    if (v) onAdd(v)
    setValue('')
  }
  return (
    <>
      <input
        className="bk-taginput"
        list={listId}
        value={value}
        maxLength={maxLength}
        placeholder="Tag…"
        aria-label={label}
        autoFocus={autoFocus}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') { e.preventDefault(); commit() }
          if (e.key === 'Escape') onClose?.()
        }}
        onBlur={() => { commit(); onClose?.() }}
      />
      <datalist id={listId}>
        {suggestions.map(s => <option key={s} value={s} />)}
      </datalist>
    </>
  )
}

function BulkBar({
  docs, isFresh, targets, suggestions, limits, busy, canEdit, canRemove,
  canDownload, onClear, onTag, onDescribe, onMove, onDownload, onRemove,
}) {
  const [tag, setTag] = useState('')
  const [desc, setDesc] = useState('')
  const [listId] = useState(() => `bk-bulk-tags-${++listSeq}`)
  const n = docs.length
  return (
    <div className="bk-bulk" role="region" aria-label="Bulk actions">
      <div className="bk-bulk-count">
        <b>{n}</b> {isFresh ? `just uploaded${canEdit ? ', tag or describe them all at once' : ''}` : 'selected'}
        <button type="button" className="bk-link" onClick={onClear}>Clear</button>
      </div>
      {canEdit && (
        <>
          <form className="bk-bulk-field"
                onSubmit={e => { e.preventDefault(); if (tag.trim()) { onTag(tag.trim()); setTag('') } }}>
            <input list={listId} value={tag} maxLength={limits.max_tag_length}
                   placeholder="Tag" aria-label="Tag to add to the selected documents"
                   onChange={e => setTag(e.target.value)} disabled={busy} />
            <datalist id={listId}>
              {suggestions.map(s => <option key={s} value={s} />)}
            </datalist>
            <button className="btn btn-sm btn-primary" disabled={busy || !tag.trim()}>Add tag</button>
          </form>
          <form className="bk-bulk-field bk-bulk-desc"
                onSubmit={e => { e.preventDefault(); onDescribe(desc.trim()); setDesc('') }}>
            <input value={desc} maxLength={limits.max_description_length}
                   placeholder="Description" aria-label="Description for the selected documents"
                   onChange={e => setDesc(e.target.value)} disabled={busy} />
            <button className="btn btn-sm btn-outline" disabled={busy}>
              {desc.trim() ? 'Set' : 'Clear'}
            </button>
          </form>
          {targets.length > 1 && (
            <select className="bk-move" value="" disabled={busy}
                    aria-label="Move the selected documents to"
                    onChange={e => e.target.value && onMove(e.target.value)}>
              <option value="">Move to…</option>
              {targets.map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          )}
        </>
      )}
      <div className="bk-bulk-end">
        {canDownload && (
          <button type="button" className="btn btn-sm btn-ghost" onClick={onDownload} disabled={busy}>
            <IconDownload /> Download
          </button>
        )}
        {canRemove && (
          <button type="button" className="btn btn-sm btn-danger-outline" onClick={onRemove} disabled={busy}>
            <IconTrash /> Remove
          </button>
        )}
      </div>
    </div>
  )
}

/** The confirm text for one document or many. The promise is the service's:
 *  `soft_delete_document` keeps the row and every version. */
export function RemoveDocumentsBody({ docs, ownerName }) {
  const names = docs.map(d => d.file_name || 'Untitled')
  return (
    <>
      <p>
        Removing {names.length === 1 ? <b>{names[0]}</b> : <b>{names.length} documents</b>}
        {ownerName ? <> from {ownerName}</> : null}.
      </p>
      {names.length > 1 && (
        <ul className="bk-confirm-list">
          {names.slice(0, 6).map((n, i) => <li key={`${n}-${i}`}>{n}</li>)}
          {names.length > 6 && <li>and {names.length - 6} more</li>}
        </ul>
      )}
      <p className="confirm-note">
        They leave this profile. The files are retained, and the removal is
        recorded in the audit trail.
      </p>
    </>
  )
}

/** A checkbox that also reports whether Shift was held: the click carries the
 *  modifier, the change event that follows it does not. */
function Check({ checked, indeterminate = false, label, onChange }) {
  const ref = useRef(null)
  const shift = useRef(false)
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate }, [indeterminate])
  return (
    <input ref={ref} type="checkbox" className="bk-check" checked={checked}
           aria-label={label}
           onClick={e => { shift.current = e.shiftKey }}
           onChange={e => { onChange(e, shift.current); shift.current = false }} />
  )
}

// ── icons: one 1.6 stroke, 16px, drawn here rather than borrowed from glyphs ──

const svg = { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }

function IconUpload() {
  return <svg {...svg}><path d="M8 10.5V2.5M4.75 5.75 8 2.5l3.25 3.25M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" /></svg>
}
function IconDownload() {
  return <svg {...svg}><path d="M8 2.5v8M4.75 7.25 8 10.5l3.25-3.25M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" /></svg>
}
function IconTrash() {
  return <svg {...svg}><path d="M2.75 4.25h10.5M6.25 4.25V2.75h3.5v1.5M4.25 4.25l.6 8.6a1 1 0 0 0 1 .9h4.3a1 1 0 0 0 1-.9l.6-8.6" /></svg>
}
function IconPlus() {
  return <svg {...svg} width={12} height={12}><path d="M8 3.5v9M3.5 8h9" /></svg>
}
function IconX() {
  return <svg {...svg} width={10} height={10}><path d="M4 4l8 8M12 4l-8 8" /></svg>
}
