import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import RemarkPopover from '@/components/orders/RemarkPopover'

const multiRemark = '[2026-07-10 15:30] C' + '\n' + '[2026-07-08 17:15] B' + '\n' + '[2026-07-01 09:00] A'

describe('RemarkPopover', () => {
  it('renders trigger', () => {
    render(<RemarkPopover remark="x"><span data-testid="t">x</span></RemarkPopover>)
    expect(screen.getByTestId('t')).toBeTruthy()
  })
  it('shows popover on hover', async () => {
    render(<RemarkPopover remark="[2026-07-01 10:00] hello"><span data-testid="t">x</span></RemarkPopover>)
    await act(async () => { fireEvent.mouseEnter(screen.getByTestId('t')) })
    await waitFor(() => { expect(screen.getByText('hello')).toBeTruthy() })
  })
  it('shows all remarks', async () => {
    render(<RemarkPopover remark={multiRemark}><span data-testid="t">x</span></RemarkPopover>)
    await act(async () => { fireEvent.mouseEnter(screen.getByTestId('t')) })
    await waitFor(() => {
      expect(screen.getByText('C')).toBeTruthy()
      expect(screen.getByText('B')).toBeTruthy()
      expect(screen.getByText('A')).toBeTruthy()
    })
  })
  it('reverse order', async () => {
    render(<RemarkPopover remark={multiRemark}><span data-testid="t">x</span></RemarkPopover>)
    await act(async () => { fireEvent.mouseEnter(screen.getByTestId('t')) })
    await waitFor(() => {
      const items = screen.getAllByTestId('remark-popover-item')
      expect(items.length).toBe(3)
      expect(items[0].textContent).toContain('C')
    })
  })
  it('empty shows placeholder', async () => {
    render(<RemarkPopover remark=""><span data-testid="t">x</span></RemarkPopover>)
    await act(async () => { fireEvent.mouseEnter(screen.getByTestId('t')) })
    await waitFor(() => { expect(screen.getByText('暂无备注')).toBeTruthy() })
  })
  it('null shows placeholder', async () => {
    render(<RemarkPopover remark={null as any}><span data-testid="t">x</span></RemarkPopover>)
    await act(async () => { fireEvent.mouseEnter(screen.getByTestId('t')) })
    await waitFor(() => { expect(screen.getByText('暂无备注')).toBeTruthy() })
  })
})
