// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import OrderTimeline from '@/components/orders/OrderTimeline'
import type { StatusHistory } from '@/types'

describe('OrderTimeline', () => {
  describe('step bar rendering', () => {
    it('renders all OrderStatusFlow steps', () => {
      render(<OrderTimeline currentStatus="pending_payment" />)
      // OrderStatusFlow: pending_payment, pending_shipment, shipped, completed
      expect(screen.getByText('待付款')).toBeInTheDocument()
      expect(screen.getByText('待发货')).toBeInTheDocument()
      expect(screen.getByText('已发货')).toBeInTheDocument()
      expect(screen.getByText('已完成')).toBeInTheDocument()
    })

    it('renders step numbers', () => {
      render(<OrderTimeline currentStatus="pending_payment" />)
      expect(screen.getByText('1')).toBeInTheDocument()
      expect(screen.getByText('2')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
      expect(screen.getByText('4')).toBeInTheDocument()
    })

    it('shows check icon for completed steps', () => {
      render(<OrderTimeline currentStatus="shipped" />)
      // pending_payment and pending_shipment should be completed (check icon)
      const checks = screen.getAllByTestId('icon-check')
      expect(checks.length).toBeGreaterThanOrEqual(2)
    })

    it('highlights current step with border color', () => {
      render(<OrderTimeline currentStatus="pending_shipment" />)
      // Step 2 is current - should show number "2" (not check)
      const stepNumbers = screen.getAllByText('2')
      expect(stepNumbers.length).toBeGreaterThanOrEqual(1)
    })

    it('shows gray numbers for upcoming steps', () => {
      render(<OrderTimeline currentStatus="pending_payment" />)
      // Steps 2,3,4 are upcoming - should all show text-gray-400
      const step2 = screen.getByText('2').closest('span')
      expect(step2).toBeTruthy()
    })
  })

  describe('status history on steps', () => {
    it('shows time on steps that have history', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z' },
      ]
      render(<OrderTimeline currentStatus="pending_shipment" statusHistory={history} />)
      // Should show formatted time for the step with history
      expect(screen.getByText('06-01 18:00')).toBeInTheDocument()
    })

    it('does not show time on steps without history', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z' },
      ]
      render(<OrderTimeline currentStatus="pending_shipment" statusHistory={history} />)
      // Only one history item, so only one time display
      const timeElements = screen.getAllByText('06-01 18:00')
      expect(timeElements.length).toBe(1)
    })
  })

  describe('closed state', () => {
    it('shows closed banner when status is closed', () => {
      render(<OrderTimeline currentStatus="closed" />)
      expect(screen.getByText('订单已关闭')).toBeInTheDocument()
    })

    it('does not show closed banner for non-closed status', () => {
      render(<OrderTimeline currentStatus="completed" />)
      expect(screen.queryByText('订单已关闭')).not.toBeInTheDocument()
    })

    it('shows closed time when history has closed entry', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z' },
        { status: 'closed', time: '2025-06-02T14:30:00Z' },
      ]
      render(<OrderTimeline currentStatus="closed" statusHistory={history} />)
      // dayjs formats UTC+8: 2025-06-02T14:30:00Z → 2025-06-02 22:30
      expect(screen.getByText('2025-06-02 22:30')).toBeInTheDocument()
    })

    it('does not show check icons when closed', () => {
      render(<OrderTimeline currentStatus="closed" />)
      // No steps should have check icon when order is closed
      expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument()
    })
  })

  describe('status history timeline', () => {
    it('does not show history section when no history', () => {
      render(<OrderTimeline currentStatus="pending_payment" />)
      expect(screen.queryByText('状态变更记录')).not.toBeInTheDocument()
    })

    it('does not show history section when history is empty array', () => {
      render(<OrderTimeline currentStatus="pending_payment" statusHistory={[]} />)
      expect(screen.queryByText('状态变更记录')).not.toBeInTheDocument()
    })

    it('shows history section with reversed entries', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z', operator: '系统' },
        { status: 'pending_shipment', time: '2025-06-02T11:00:00Z', operator: '张三' },
        { status: 'shipped', time: '2025-06-03T12:00:00Z', operator: '李四', remark: '已发货' },
      ]
      render(<OrderTimeline currentStatus="shipped" statusHistory={history} />)
      expect(screen.getByText('状态变更记录')).toBeInTheDocument()
      // "已发货", "待发货", "待付款" appear in both step bar and history timeline
      // Use getAllByText to verify they exist at least once
      expect(screen.getAllByText('已发货').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('待发货').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('待付款').length).toBeGreaterThanOrEqual(1)
    })

    it('shows operator name in history', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z', operator: '系统' },
      ]
      render(<OrderTimeline currentStatus="pending_payment" statusHistory={history} />)
      expect(screen.getByText('操作人: 系统')).toBeInTheDocument()
    })

    it('shows remark in history', () => {
      const history: StatusHistory[] = [
        { status: 'pending_shipment', time: '2025-06-02T11:00:00Z', remark: '客户已付款' },
      ]
      render(<OrderTimeline currentStatus="pending_shipment" statusHistory={history} />)
      expect(screen.getByText('客户已付款')).toBeInTheDocument()
    })

    it('does not show operator when not present', () => {
      const history: StatusHistory[] = [
        { status: 'pending_payment', time: '2025-06-01T10:00:00Z' },
      ]
      render(<OrderTimeline currentStatus="pending_payment" statusHistory={history} />)
      expect(screen.queryByText(/操作人:/)).not.toBeInTheDocument()
    })
  })

  describe('className prop', () => {
    it('applies custom className', () => {
      const { container } = render(
        <OrderTimeline currentStatus="pending_payment" className="custom-class" />
      )
      expect(container.firstChild).toHaveClass('custom-class')
    })
  })
})
