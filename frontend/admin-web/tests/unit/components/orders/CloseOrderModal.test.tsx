// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import CloseOrderModal from '@/components/orders/CloseOrderModal'

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onConfirm: vi.fn(),
}

describe('CloseOrderModal', () => {
  describe('rendering', () => {
    it('renders when open is true', () => {
      render(<CloseOrderModal {...defaultProps} />)
      expect(screen.getByText('关闭订单')).toBeInTheDocument()
      expect(screen.getByText('确定关闭当前订单吗？关闭订单不可恢复。')).toBeInTheDocument()
    })

    it('does not render when open is false', () => {
      render(<CloseOrderModal {...defaultProps} open={false} />)
      expect(screen.queryByText('关闭订单')).not.toBeInTheDocument()
    })

    it('renders preset reason radio options', () => {
      render(<CloseOrderModal {...defaultProps} />)
      expect(screen.getByText('缺货')).toBeInTheDocument()
      expect(screen.getByText('过期未付款')).toBeInTheDocument()
      expect(screen.getByText('协商一致')).toBeInTheDocument()
      expect(screen.getByText('备注其它原因')).toBeInTheDocument()
    })

    it('renders cancel and confirm buttons', () => {
      render(<CloseOrderModal {...defaultProps} />)
      expect(screen.getByText('取消')).toBeInTheDocument()
      expect(screen.getByText('确定')).toBeInTheDocument()
    })

    it('renders warning icon and message', () => {
      render(<CloseOrderModal {...defaultProps} />)
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument()
    })
  })

  describe('radio selection', () => {
    it('selects first preset reason by default', () => {
      render(<CloseOrderModal {...defaultProps} />)
      const radio = screen.getByDisplayValue('缺货') as HTMLInputElement
      expect(radio.checked).toBe(true)
    })

    it('switches to another preset reason on click', () => {
      render(<CloseOrderModal {...defaultProps} />)
      const radio = screen.getByDisplayValue('过期未付款') as HTMLInputElement
      fireEvent.click(radio)
      expect(radio.checked).toBe(true)
    })

    it('shows textarea when "备注其它原因" is selected', () => {
      render(<CloseOrderModal {...defaultProps} />)
      const otherRadio = screen.getByDisplayValue('备注其它原因') as HTMLInputElement
      fireEvent.click(otherRadio)
      expect(screen.getByPlaceholderText('请输入关闭原因')).toBeInTheDocument()
    })

    it('hides textarea when switching back from "备注其它原因"', () => {
      render(<CloseOrderModal {...defaultProps} />)
      // Select other first
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      expect(screen.getByPlaceholderText('请输入关闭原因')).toBeInTheDocument()
      // Switch back to preset
      fireEvent.click(screen.getByDisplayValue('缺货'))
      expect(screen.queryByPlaceholderText('请输入关闭原因')).not.toBeInTheDocument()
    })
  })

  describe('confirm action', () => {
    it('calls onConfirm with selected preset reason', () => {
      const onConfirm = vi.fn()
      render(<CloseOrderModal {...defaultProps} onConfirm={onConfirm} />)
      fireEvent.click(screen.getByText('确定'))
      expect(onConfirm).toHaveBeenCalledWith('缺货')
    })

    it('calls onConfirm with other text when other is selected', () => {
      const onConfirm = vi.fn()
      render(<CloseOrderModal {...defaultProps} onConfirm={onConfirm} />)
      // Select "备注其它原因"
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      // Type custom text
      fireEvent.change(screen.getByPlaceholderText('请输入关闭原因'), {
        target: { value: '客户要求关闭' },
      })
      fireEvent.click(screen.getByText('确定'))
      expect(onConfirm).toHaveBeenCalledWith('客户要求关闭')
    })

    it('does not call onConfirm when other text is empty', () => {
      const onConfirm = vi.fn()
      render(<CloseOrderModal {...defaultProps} onConfirm={onConfirm} />)
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      fireEvent.click(screen.getByText('确定'))
      expect(onConfirm).not.toHaveBeenCalled()
    })

    it('disables confirm button when other is selected but text is empty', () => {
      render(<CloseOrderModal {...defaultProps} />)
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      const confirmBtn = screen.getByText('确定')
      expect(confirmBtn).toBeDisabled()
    })

    it('enables confirm button when other text is entered', () => {
      render(<CloseOrderModal {...defaultProps} />)
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      fireEvent.change(screen.getByPlaceholderText('请输入关闭原因'), {
        target: { value: '原因' },
      })
      const confirmBtn = screen.getByText('确定')
      expect(confirmBtn).not.toBeDisabled()
    })
  })

  describe('close action', () => {
    it('calls onClose when cancel button is clicked', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} />)
      fireEvent.click(screen.getByText('取消'))
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('calls onClose when X button is clicked', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} />)
      fireEvent.click(screen.getByTestId('icon-x'))
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('calls onClose on ESC key', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} />)
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('does not call onClose on ESC when closed', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} open={false} />)
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(onClose).not.toHaveBeenCalled()
    })

    it('calls onClose when backdrop is clicked', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} />)
      const backdrop = document.querySelector('.bg-black\\/45')
      fireEvent.click(backdrop!)
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  describe('loading state', () => {
    it('disables close and confirm buttons when loading', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} loading={true} />)
      expect(screen.getByText('取消')).toBeDisabled()
      expect(screen.getByText('确定')).toBeDisabled()
    })

    it('does not call onClose when backdrop is clicked during loading', () => {
      const onClose = vi.fn()
      render(<CloseOrderModal {...defaultProps} onClose={onClose} loading={true} />)
      const backdrop = document.querySelector('.bg-black\\/45')
      fireEvent.click(backdrop!)
      expect(onClose).not.toHaveBeenCalled()
    })

    it('shows loading spinner on confirm button', () => {
      render(<CloseOrderModal {...defaultProps} loading={true} />)
      // The Button component renders Loader2 when loading
      expect(screen.getByTestId('icon-loader2')).toBeInTheDocument()
    })
  })

  describe('body scroll lock', () => {
    it('sets body overflow to hidden when open', () => {
      render(<CloseOrderModal {...defaultProps} />)
      expect(document.body.style.overflow).toBe('hidden')
    })

    it('restores body overflow on unmount', () => {
      const { unmount } = render(<CloseOrderModal {...defaultProps} />)
      unmount()
      expect(document.body.style.overflow).toBe('')
    })
  })

  describe('state reset on reopen', () => {
    it('resets selection to first preset when reopened', () => {
      const { rerender } = render(<CloseOrderModal {...defaultProps} />)
      // Select other first
      fireEvent.click(screen.getByDisplayValue('备注其它原因'))
      fireEvent.change(screen.getByPlaceholderText('请输入关闭原因'), {
        target: { value: '客户取消' },
      })

      // Close then reopen
      rerender(<CloseOrderModal {...defaultProps} open={false} />)
      rerender(<CloseOrderModal {...defaultProps} open={true} />)

      // Should be back to first preset
      const radio = screen.getByDisplayValue('缺货') as HTMLInputElement
      expect(radio.checked).toBe(true)
      expect(screen.queryByPlaceholderText('请输入关闭原因')).not.toBeInTheDocument()
    })
  })
})
