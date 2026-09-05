// case_ids: HR-002
// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import Modal from '@/components/ui/Modal'

describe('Modal Component', () => {
  it('renders when open is true', () => {
    render(<Modal open onClose={vi.fn()}>Content</Modal>)
    expect(screen.getByText('Content')).toBeInTheDocument()
  })

  it('does not render when open is false', () => {
    render(<Modal open={false} onClose={vi.fn()}>Content</Modal>)
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
  })

  it('renders title', () => {
    render(<Modal open onClose={vi.fn()} title="Modal Title">Content</Modal>)
    expect(screen.getByText('Modal Title')).toBeInTheDocument()
  })

  it('does not render title when not provided', () => {
    render(<Modal open onClose={vi.fn()}>Content</Modal>)
    expect(screen.queryByText('Modal Title')).not.toBeInTheDocument()
  })

  it('renders footer when provided', () => {
    render(<Modal open onClose={vi.fn()} footer={<button>Save</button>}>Content</Modal>)
    expect(screen.getByText('Save')).toBeInTheDocument()
  })

  it('renders default footer with 取消 and 确定 buttons when footer not provided', () => {
    render(<Modal open onClose={vi.fn()}>Content</Modal>)
    expect(screen.getByText('取消')).toBeInTheDocument()
    expect(screen.getByText('确定')).toBeInTheDocument()
  })

  it('calls onClose when X button is clicked', () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose} title="Title">Content</Modal>)
    // X icon is mocked as span[data-testid="icon-x"]
    fireEvent.click(screen.getByTestId('icon-x'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when mask is clicked (maskClosable=true)', () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose} maskClosable>Content</Modal>)
    // First div is the mask layer (bg-black/45)
    const mask = document.querySelector('.bg-black\\/45')
    fireEvent.click(mask!)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does NOT call onClose when mask is clicked and maskClosable=false', () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose} maskClosable={false}>Content</Modal>)
    const mask = document.querySelector('.bg-black\\/45')
    fireEvent.click(mask!)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose on ESC key', () => {
    const onClose = vi.fn()
    render(<Modal open onClose={onClose}>Content</Modal>)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does NOT show X button when closable=false', () => {
    render(<Modal open onClose={vi.fn()} title="Title" closable={false}>Content</Modal>)
    expect(screen.queryByTestId('icon-x')).not.toBeInTheDocument()
  })

  it('sets body overflow hidden on mount when open', () => {
    render(<Modal open onClose={vi.fn()}>Content</Modal>)
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('resets body overflow on unmount', () => {
    const { unmount } = render(<Modal open onClose={vi.fn()}>Content</Modal>)
    unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('#2907: 内容超高时弹窗高度受限，标题与底部按钮一屏可见（内容区内部滚动）', () => {
    render(
      <Modal open onClose={vi.fn()} title="弹窗标题" footer={<button>保存</button>}>
        <div className="h-[2000px]" />
      </Modal>
    )
    const dialog = screen.getByRole('dialog')
    // 弹窗整体受视口高度约束（max-h-full + flex-col），标题/底部按钮常驻一屏内
    expect(dialog.className).toContain('max-h-full')
    expect(dialog.className).toContain('flex-col')
    // 内容区超高时内部滚动（overflow-y-auto）
    const body = within(dialog).getByTestId('modal-body')
    expect(body.className).toContain('overflow-y-auto')
    // 标题与底部按钮仍在 DOM 中可见
    expect(within(dialog).getByRole('heading', { name: '弹窗标题' })).toBeInTheDocument()
    expect(within(dialog).getByText('保存')).toBeInTheDocument()
  })
})
