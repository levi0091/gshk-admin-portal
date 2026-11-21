import { describe, it, expect, vi } from 'vitest'
import {
  fetchRemote, looksLikeFileDrag, parseDownloadUrl, readDrop, REMOTE_REFUSED,
} from './dropFiles.js'

const file = name => new File(['x'], name)

describe('looksLikeFileDrag', () => {
  it('is a file drag for files and for webmail attachments', () => {
    expect(looksLikeFileDrag({ types: ['Files'] })).toBe(true)
    expect(looksLikeFileDrag({ types: ['text/uri-list', 'DownloadURL'] })).toBe(true)
  })
  it('is not one for text or a link', () => {
    expect(looksLikeFileDrag({ types: ['text/plain'] })).toBe(false)
    expect(looksLikeFileDrag({ types: ['text/uri-list'] })).toBe(false)
    expect(looksLikeFileDrag(null)).toBe(false)
  })
})

describe('readDrop', () => {
  it('reads files from items, which is how an Outlook attachment arrives', () => {
    const f = file('outlook.msg')
    const out = readDrop({ items: [{ kind: 'file', getAsFile: () => f }, { kind: 'string' }],
                           files: [], getData: () => '' })
    expect(out.files).toEqual([f])
    expect(out.remote).toBeNull()
  })
  it('falls back to files', () => {
    const f = file('a.pdf')
    expect(readDrop({ items: [], files: [f], getData: () => '' }).files).toEqual([f])
  })
  it('skips a folder (getAsFile is null)', () => {
    const out = readDrop({ items: [{ kind: 'file', getAsFile: () => null }], files: [],
                           getData: () => '' })
    expect(out.files).toEqual([])
  })
  it('takes a DownloadURL when there is no file', () => {
    const out = readDrop({ items: [], files: [],
      getData: t => (t === 'DownloadURL' ? 'application/pdf:bill.pdf:https://x.test/a?b=c:d' : '') })
    expect(out.remote).toEqual({ mime: 'application/pdf', name: 'bill.pdf', url: 'https://x.test/a?b=c:d' })
  })
  it('takes a bare URI list as a last resort', () => {
    const out = readDrop({ items: [], files: [],
      getData: t => (t === 'text/uri-list' ? '# comment\nhttps://x.test/files/Report%201.pdf?x=1' : '') })
    expect(out.remote.name).toBe('Report 1.pdf')
  })
  it('survives a browser that throws on getData', () => {
    expect(readDrop({ items: [], files: [], getData: () => { throw new Error('nope') } }))
      .toEqual({ files: [], remote: null })
  })
})

describe('parseDownloadUrl', () => {
  it('refuses anything that is not http(s)', () => {
    expect(parseDownloadUrl('text/plain:a.txt:javascript:alert(1)')).toBeNull()
    expect(parseDownloadUrl('garbage')).toBeNull()
  })
})

describe('fetchRemote', () => {
  it('turns a readable attachment into a File', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob(['%PDF'])) })
    const f = await fetchRemote({ name: 'bill.pdf', url: 'https://x.test/a', mime: 'application/pdf' }, fetchImpl)
    expect(f.name).toBe('bill.pdf')
    expect(f.type).toBe('application/pdf')
  })
  it('says what to do when the provider refuses', async () => {
    const remote = { name: 'a', url: 'https://x.test', mime: '' }
    await expect(fetchRemote(remote, vi.fn().mockRejectedValue(new TypeError('cors'))))
      .rejects.toThrow(REMOTE_REFUSED)
    await expect(fetchRemote(remote, vi.fn().mockResolvedValue({ ok: false })))
      .rejects.toThrow(REMOTE_REFUSED)
  })
})
