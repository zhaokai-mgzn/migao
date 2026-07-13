/**
 * RemarkPopover component tests
 * Covers: trigger render, popover show/hide, remark parsing,
 *         reverse order, empty state, operator display,
 *         remarks[] array support, instant hover (#1289)
 */
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import RemarkPopover from '@/components/orders/RemarkPopover'
import type { OrderRemark } from '@/types'

vi.mock('react-dom', async () => {
  const actual = await vi.importActual('react-dom')
  return {
    ...actual,
    createPortal: (children: React.ReactNode) => children,
  }
})

describe('RemarkPopover', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const triggerText = '💬 测试备注预览'

  it('renders trigger content', () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 客户催单">
        <span>{triggerText}</span>
      </RemarkPopover>
    )
    expect(screen.getByText(triggerText)).toBeTruthy()
  })

  it('shows popover immediately on hover (no delay, #1289)', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 客户催单">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('客户催单')).toBeTruthy()
    expect(screen.getByText('2026-07-01 10:00')).toBeTruthy()
  })

  it('hides popover immediately on mouse leave', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 测试">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(screen.getByText('测试')).toBeTruthy()

    await act(async () => {
      fireEvent.mouseLeave(trigger)
    })
    expect(screen.queryByText('测试')).toBeNull()
  })

  it('displays all multiple remarks', async () => {
    const remark = [
      '[2026-07-01 09:00] A下单确认',
      '[2026-07-08 10:00] B客户要求加急',
      '[2026-07-10 15:00] C更新物流单号',
    ].join('\n')

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('C更新物流单号')).toBeTruthy()
    expect(screen.getByText('B客户要求加急')).toBeTruthy()
    expect(screen.getByText('A下单确认')).toBeTruthy()
  })

  it('sorts remarks in reverse chronological order', async () => {
    const remark = [
      '[2026-07-01 09:00] A最早备注',
      '[2026-07-08 10:00] B中间备注',
      '[2026-07-10 15:00] C最新备注',
    ].join('\n')

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0].textContent).toContain('C最新备注')
    expect(items[1].textContent).toContain('B中间备注')
    expect(items[2].textContent).toContain('A最早备注')
  })

  it('shows placeholder for empty remark', async () => {
    render(
      <RemarkPopover remark="">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('暂无备注')).toBeTruthy()
  })

  it('shows placeholder for null remark', async () => {
    render(
      <RemarkPopover remark={null}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('暂无备注')).toBeTruthy()
  })

  it('displays single remark correctly', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 仅一条备注">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('仅一条备注')).toBeTruthy()
    expect(screen.getByText('2026-07-01 10:00')).toBeTruthy()
  })

  it('displays long remark content in full', async () => {
    const longText = 'A'.repeat(300)
    const remark = `[2026-07-01 10:00] ${longText}`

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText(longText)).toBeTruthy()
  })

  it('escapes special characters in remarks', async () => {
    const remark = '[2026-07-01 10:00] <script>alert("xss")</script> & emoji 🎉'

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    const content = screen.getByText(/script/)
    expect(content).toBeTruthy()
    expect(content.textContent).toContain('<script>alert("xss")</script>')
    expect(content.textContent).toContain('🎉')
  })

  it('renders tooltip with triangle arrow', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 测试">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeTruthy()
  })

  it('displays remark without timestamp prefix', async () => {
    const remark = '纯文本备注，无时间戳'

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('纯文本备注，无时间戳')).toBeTruthy()
  })

  // #1289: operator display from string format
  it('displays operator name when present in remark string', async () => {
    const remark = '[2026-07-13 10:00] 客户催单 [操作人: 张三]'

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText(/张三/)).toBeTruthy()
  })

  // #1289: remarks[] array support
  it('supports remarks array format (structured data)', async () => {
    const remarks: OrderRemark[] = [
      { id: '1', content: '客户联系要求加急', createdAt: '2026-07-13 10:00:00', operator: '张三' },
      { id: '2', content: '已联系供应商', createdAt: '2026-07-12 09:00:00' },
    ]

    render(
      <RemarkPopover remarks={remarks}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('客户联系要求加急')).toBeTruthy()
    expect(screen.getByText('已联系供应商')).toBeTruthy()
    expect(screen.getByText(/张三/)).toBeTruthy()
    expect(screen.getByText('2026-07-13 10:00')).toBeTruthy()
    expect(screen.getByText('2026-07-12 09:00')).toBeTruthy()
  })

  // #1289: remarks[] array reverse order
  it('sorts remarks array by createdAt descending', async () => {
    const remarks: OrderRemark[] = [
      { id: '1', content: 'A最早', createdAt: '2026-07-10T09:00:00Z' },
      { id: '2', content: 'B中间', createdAt: '2026-07-12T10:00:00Z' },
      { id: '3', content: 'C最新', createdAt: '2026-07-13T16:00:00Z' },
    ]

    render(
      <RemarkPopover remarks={remarks}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0].textContent).toContain('C最新')
    expect(items[1].textContent).toContain('B中间')
    expect(items[2].textContent).toContain('A最早')
  })

  // #1289: no operator placeholder when operator is absent
  it('does not render operator element when operator is missing', async () => {
    const remarks: OrderRemark[] = [
      { id: '1', content: '普通备注', createdAt: '2026-07-13T10:00:00Z' },
    ]

    render(
      <RemarkPopover remarks={remarks}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })

    expect(screen.getByText('普通备注')).toBeTruthy()
    const items = screen.getAllByRole('listitem')
    expect(items[0].querySelector('[data-operator]')).toBeNull()
  })

  // #1289: trigger span uses block w-full for full cell coverage
  it('trigger span has block w-full class for full cell coverage', () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 测试">
        <span data-testid="trigger-content">{triggerText}</span>
      </RemarkPopover>
    )

    const triggerContent = screen.getByTestId('trigger-content')
    const triggerSpan = triggerContent.parentElement
    expect(triggerSpan).toBeTruthy()
    const classes = triggerSpan!.className.split(/\s+/)
    expect(classes).toContain('block')
    expect(classes).toContain('w-full')
    expect(classes).not.toContain('inline-block')
  })
})
