import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FileDropZone from './FileDropZone.jsx'

const pdf = name => new File(['x'], name, { type: 'application/pdf' })
const zone = () => screen.getByRole('button', { name: /Drag files here/ })

describe('FileDropZone', () => {
  it('hands over every dropped file', () => {
    const onFiles = vi.fn()
    render(<FileDropZone onFiles={onFiles} />)
    const files = [pdf('a.pdf'), pdf('b.pdf')]
    fireEvent.drop(zone(), { dataTransfer: { files } })
    expect(onFiles).toHaveBeenCalledWith(files)
  })

  it('hands over a file picked from the dialog', async () => {
    const onFiles = vi.fn()
    render(<FileDropZone onFiles={onFiles} />)
    await userEvent.setup().upload(screen.getByLabelText('Choose file'), pdf('a.pdf'))
    expect(onFiles.mock.calls[0][0][0].name).toBe('a.pdf')
  })

  it('lights up while a file is held over it, and stops when it leaves', () => {
    render(<FileDropZone onFiles={vi.fn()} />)
    fireEvent.dragOver(zone())
    expect(zone()).toHaveClass('is-over')
    fireEvent.dragLeave(zone())
    expect(zone()).not.toHaveClass('is-over')
  })

  it('takes nothing while an upload is running', () => {
    const onFiles = vi.fn()
    render(<FileDropZone onFiles={onFiles} busy />)
    const busy = screen.getByRole('button', { name: 'Uploading…' })
    expect(busy).toBeDisabled()
    fireEvent.drop(busy, { dataTransfer: { files: [pdf('a.pdf')] } })
    expect(onFiles).not.toHaveBeenCalled()
  })

  it('stops a file dropped beside it from opening in place of the portal', () => {
    const { unmount } = render(<FileDropZone onFiles={vi.fn()} />)
    expect(fireEvent.drop(window)).toBe(false) // false: default prevented
    unmount()
    expect(fireEvent.drop(window)).toBe(true)
  })
})
