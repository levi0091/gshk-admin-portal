import { useEffect, useRef, useState } from 'react'

/**
 * Drag files onto it, or press it to pick them. It hands over the files the
 * moment it has them; there is no second Upload press.
 *
 * WHILE IT IS ON SCREEN THE WINDOW IGNORES A DROP. A file let go a few pixels
 * outside the zone would otherwise make the browser open it in place of the
 * portal, and take whatever was keyed on the page with it.
 */
export default function FileDropZone({ onFiles, busy = false, sub, label = 'Choose file' }) {
  const input = useRef(null)
  const [over, setOver] = useState(false)

  useEffect(() => {
    const ignore = e => e.preventDefault()
    window.addEventListener('dragover', ignore)
    window.addEventListener('drop', ignore)
    return () => {
      window.removeEventListener('dragover', ignore)
      window.removeEventListener('drop', ignore)
    }
  }, [])

  function take(list) {
    const files = Array.from(list || [])
    if (files.length && !busy) onFiles(files)
  }

  return (
    <>
      <input ref={input} type="file" multiple aria-label={label} style={{ display: 'none' }}
             onChange={e => { take(e.target.files); e.target.value = '' }} />
      <button type="button" className={`drop-zone ${over ? 'is-over' : ''}`} disabled={busy}
              onClick={() => input.current?.click()}
              onDragOver={e => { e.preventDefault(); setOver(true) }}
              onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(false) }}
              onDrop={e => { e.preventDefault(); setOver(false); take(e.dataTransfer.files) }}>
        {busy ? <div>Uploading…</div> : (
          <>
            <div>Drag files here, or <span className="dz-link">choose files</span></div>
            {sub && <div className="dz-sub">{sub}</div>}
          </>
        )}
      </button>
    </>
  )
}
