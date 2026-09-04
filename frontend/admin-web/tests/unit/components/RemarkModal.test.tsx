// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import RemarkModal from '@/components/orders/RemarkModal'

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onConfirm: vi.fn(),
}

describe('RemarkModal', () => {
  describe('rendering', () => {
    it('renders when open is true', () => {
      render(<RemarkModal {...defaultProps} />)
      expect(screen.getByText('添加备注')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('请输入备注内容')).toBeInTheDocument()
    })

    it('does not render when open is false', () => {
      render(<RemarkModal {...defaultProps} open={false} />)
      expect(screen.queryByText('添加备注')).not.toBeInTheDocument()
    })

    it('renders cancel and confirm buttons', () => {
      render(<RemarkModal {...defaultProps} />)
      expect(screen.getByText('取消')).toBeInTheDocument()
      expect(screen.getByText('确认')).toBeInTheDocument()
    })

    it('confirm button is disabled when content is empty', () => {
      render(<RemarkModal {...defaultProps} />)
      expect(screen.getByText('确认')).toBeDisabled()
    })
  })

  describe('textarea input', () => {
    it('updates textarea value when typing', () => {
      render(<RemarkModal {...defaultProps} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容') as HTMLTextAreaElement
      fireEvent.change(textarea, { target: { value: '这是一条备注' } })
      expect(textarea.value).toBe('这是一条备注')
    })

    it('enables confirm button when text is entered', () => {
      render(<RemarkModal {...defaultProps} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容')
      fireEvent.change(textarea, { target: { value: '备注' } })
      expect(screen.getByText('确认')).not.toBeDisabled()
    })

    it('disables confirm button for whitespace-only content', () => {
      render(<RemarkModal {...defaultProps} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容')
      fireEvent.change(textarea, { target: { value: '   ' } })
      expect(screen.getByText('确认')).toBeDisabled()
    })
  })

  describe('confirm action', () => {
    it('calls onConfirm with trimmed content', () => {
      const onConfirm = vi.fn()
      render(<RemarkModal {...defaultProps} onConfirm={onConfirm} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容')
      fireEvent.change(textarea, { target: { value: '  客户备注内容  ' } })
      fireEvent.click(screen.getByText('确认'))
      expect(onConfirm).toHaveBeenCalledWith('客户备注内容')
    })

    it('does not call onConfirm when content is empty', () => {
      const onConfirm = vi.fn()
      render(<RemarkModal {...defaultProps} onConfirm={onConfirm} />)
      fireEvent.click(screen.getByText('确认'))
      expect(onConfirm).not.toHaveBeenCalled()
    })
  })

  describe('close action', () => {
    it('calls onClose when cancel button is clicked', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} />)
      fireEvent.click(screen.getByText('取消'))
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('calls onClose when X button is clicked', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} />)
      fireEvent.click(screen.getByTestId('icon-x'))
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('calls onClose on ESC key', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} />)
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('does not call onClose on ESC when closed', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} open={false} />)
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(onClose).not.toHaveBeenCalled()
    })

    it('calls onClose when backdrop is clicked', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} />)
      const backdrop = document.querySelector('.bg-black\\/45')
      fireEvent.click(backdrop!)
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  describe('loading state', () => {
    it('disables close and confirm buttons when loading', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} loading={true} />)
      expect(screen.getByText('取消')).toBeDisabled()
      // Confirm still disabled because content is empty, but button itself is in loading state
    })

    it('does not call onClose when backdrop is clicked during loading', () => {
      const onClose = vi.fn()
      render(<RemarkModal {...defaultProps} onClose={onClose} loading={true} />)
      const backdrop = document.querySelector('.bg-black\\/45')
      fireEvent.click(backdrop!)
      expect(onClose).not.toHaveBeenCalled()
    })

    it('shows loading spinner on confirm button when loading and content is filled', () => {
      render(<RemarkModal {...defaultProps} loading={true} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容')
      fireEvent.change(textarea, { target: { value: 'test' } })
      // Button should have Loader2 icon when loading
      expect(screen.getByTestId('icon-loader2')).toBeInTheDocument()
    })
  })

  describe('body scroll lock', () => {
    it('sets body overflow to hidden when open', () => {
      render(<RemarkModal {...defaultProps} />)
      expect(document.body.style.overflow).toBe('hidden')
    })

    it('restores body overflow on unmount', () => {
      const { unmount } = render(<RemarkModal {...defaultProps} />)
      unmount()
      expect(document.body.style.overflow).toBe('')
    })
  })

  describe('state reset on reopen', () => {
    it('resets content when reopened', () => {
      const { rerender } = render(<RemarkModal {...defaultProps} />)
      const textarea = screen.getByPlaceholderText('请输入备注内容') as HTMLTextAreaElement
      fireEvent.change(textarea, { target: { value: '之前的内容' } })

      // Close then reopen
      rerender(<RemarkModal {...defaultProps} open={false} />)
      rerender(<RemarkModal {...defaultProps} open={true} />)

      const newTextarea = screen.getByPlaceholderText('请输入备注内容') as HTMLTextAreaElement
      expect(newTextarea.value).toBe('')
    })
  })
})
