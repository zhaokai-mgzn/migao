// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import dayjs from 'dayjs'
import OrderProgressSteps from '@/components/orders/OrderProgressSteps'

describe('OrderProgressSteps', () => {
  describe('step rendering', () => {
    it('renders all 4 steps', () => {
      render(<OrderProgressSteps status="pending_payment" />)
      expect(screen.getByText('已付款')).toBeInTheDocument()
      expect(screen.getByText('待发货')).toBeInTheDocument()
      expect(screen.getByText('待收货')).toBeInTheDocument()
      expect(screen.getByText('已完成')).toBeInTheDocument()
    })

    it('renders step numbers 1-4', () => {
      render(<OrderProgressSteps status="pending_payment" />)
      expect(screen.getByText('1')).toBeInTheDocument()
      expect(screen.getByText('2')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
      expect(screen.getByText('4')).toBeInTheDocument()
    })
  })

  describe('pending_payment status', () => {
    it('shows step 1 as current, steps 2-4 as upcoming', () => {
      render(<OrderProgressSteps status="pending_payment" />)
      // Step 1 is current (no check, shows number)
      expect(screen.getByText('1')).toBeInTheDocument()
      expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument()
    })
  })

  describe('pending_shipment status', () => {
    it('shows step 1 completed with check, step 2 current', () => {
      render(<OrderProgressSteps status="pending_shipment" />)
      // Step 1 should be completed (check icon)
      const checks = screen.getAllByTestId('icon-check')
      expect(checks.length).toBe(1)
      // Step 2 num should still be visible (current)
      expect(screen.getByText('2')).toBeInTheDocument()
    })
  })

  describe('shipped status', () => {
    it('shows steps 1-2 completed, step 3 current', () => {
      render(<OrderProgressSteps status="shipped" />)
      const checks = screen.getAllByTestId('icon-check')
      expect(checks.length).toBe(2)
    })
  })

  describe('completed status', () => {
    it('shows all 4 steps as completed with check icons', () => {
      render(<OrderProgressSteps status="completed" />)
      const checks = screen.getAllByTestId('icon-check')
      expect(checks.length).toBe(4)
    })

    it('does not show any step numbers when all completed', () => {
      render(<OrderProgressSteps status="completed" />)
      // All steps show check, no numbers
      expect(screen.queryByText('1')).not.toBeInTheDocument()
    })
  })

  describe('closed and refund status', () => {
    it('shows all steps as upcoming for closed status', () => {
      render(<OrderProgressSteps status="closed" />)
      expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument()
      // All numbers should be visible
      expect(screen.getByText('1')).toBeInTheDocument()
      expect(screen.getByText('2')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
      expect(screen.getByText('4')).toBeInTheDocument()
    })

    it('shows all steps as upcoming for refund status', () => {
      render(<OrderProgressSteps status="refund" />)
      expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument()
      expect(screen.getByText('1')).toBeInTheDocument()
    })
  })

  describe('time display', () => {
    // Use dayjs to compute expected values dynamically, matching the component's fmt()
    // This avoids timezone-dependent failures between local (UTC+8) and CI (UTC).
    function fmt(time: string): string {
      return dayjs(time).format('YYYY-MM-DD HH:mm')
    }

    it('shows paidAt time on step 1 and step 2 when status is pending_shipment', () => {
      const paidAt = '2025-06-15T08:30:00Z'
      render(
        <OrderProgressSteps
          status="pending_shipment"
          paidAt={paidAt}
        />
      )
      // Both step 1 (completed) and step 2 (current) use paidAt, so time appears twice
      const expected = fmt(paidAt)
      const times = screen.getAllByText(expected)
      expect(times.length).toBe(2)
    })

    it('shows shippedAt time on step 3 when provided and status is shipped', () => {
      const paidAt = '2025-06-15T08:30:00Z'
      const shippedAt = '2025-06-16T10:00:00Z'
      render(
        <OrderProgressSteps
          status="shipped"
          paidAt={paidAt}
          shippedAt={shippedAt}
        />
      )
      // step 3 time is unique (shippedAt), step 1-2 both use paidAt
      expect(screen.getByText(fmt(shippedAt))).toBeInTheDocument()
      // paidAt also appears on step 1-2
      expect(screen.getAllByText(fmt(paidAt)).length).toBe(2)
    })

    it('shows receivedAt time on step 4 when status is completed', () => {
      const paidAt = '2025-06-15T08:30:00Z'
      const shippedAt = '2025-06-16T10:00:00Z'
      const receivedAt = '2025-06-18T14:00:00Z'
      render(
        <OrderProgressSteps
          status="completed"
          paidAt={paidAt}
          shippedAt={shippedAt}
          receivedAt={receivedAt}
        />
      )
      // step 4 time is unique (receivedAt)
      expect(screen.getByText(fmt(receivedAt))).toBeInTheDocument()
    })

    it('shows time only for current step when status is pending_payment', () => {
      const paidAt = '2025-06-15T08:30:00Z'
      render(
        <OrderProgressSteps
          status="pending_payment"
          paidAt={paidAt}
        />
      )
      // Step 1 is current → time shown. Steps 2-4 are upcoming → no time shown.
      // Only step 1 shows the time since step 2 is upcoming (not current/completed)
      const expected = fmt(paidAt)
      const times = screen.getAllByText(expected)
      expect(times.length).toBe(1)
    })

    it('does not show time placeholder when not provided', () => {
      render(<OrderProgressSteps status="completed" />)
      // No time text with YYYY-MM-DD format should appear
      expect(screen.queryByText(/\d{4}-\d{2}-\d{2}/)).not.toBeInTheDocument()
    })
  })

  describe('label styling', () => {
    it('completed step labels use text-gray-900', () => {
      render(<OrderProgressSteps status="completed" />)
      const label = screen.getByText('已付款')
      expect(label.className).toContain('text-gray-900')
    })

    it('upcoming step labels use text-gray-400', () => {
      render(<OrderProgressSteps status="pending_payment" />)
      // Step 4 "已完成" is upcoming
      const label = screen.getByText('已完成')
      expect(label.className).toContain('text-gray-400')
    })
  })
})
