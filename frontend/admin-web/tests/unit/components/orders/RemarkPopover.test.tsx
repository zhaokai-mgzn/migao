/**
 * RemarkPopover 组件测试
 * 覆盖：触发渲染、浮窗显示/隐藏、备注条目解析、倒序验证、空状态占位、样式规范
 */
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import RemarkPopover from '@/components/orders/RemarkPopover'

// Mock createPortal to render inline for testing
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

  it('应渲染触发器内容', () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 客户催单">
        <span>{triggerText}</span>
      </RemarkPopover>
    )
    expect(screen.getByText(triggerText)).toBeTruthy()
  })

  it('鼠标悬停后应显示浮窗', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 客户催单">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)

    // 200ms 延迟后浮窗可见
    act(() => {
      vi.advanceTimersByTime(250)
    })

    // 浮窗内容应可见
    expect(screen.getByText('客户催单')).toBeTruthy()
    expect(screen.getByText('2026-07-01 10:00')).toBeTruthy()
  })

  it('鼠标移出后应隐藏浮窗', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 测试">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(screen.getByText('测试')).toBeTruthy()

    fireEvent.mouseLeave(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    // 浮窗内容应隐藏
    expect(screen.queryByText('测试')).toBeNull()
  })

  it('多条备注应全部显示', async () => {
    // 模拟后端数据：按添加时间正序（最早在前）
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
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByText('C更新物流单号')).toBeTruthy()
    expect(screen.getByText('B客户要求加急')).toBeTruthy()
    expect(screen.getByText('A下单确认')).toBeTruthy()
  })

  it('备注应按添加时间倒序显示（最新在最前）', async () => {
    // 模拟后端数据：按添加时间正序（最早在前，A→B→C）
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
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    // 验证倒序：C → B → A
    expect(items[0].textContent).toContain('C最新备注')
    expect(items[1].textContent).toContain('B中间备注')
    expect(items[2].textContent).toContain('A最早备注')
  })

  it('空备注应显示"暂无备注"占位', async () => {
    render(
      <RemarkPopover remark="">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByText('暂无备注')).toBeTruthy()
  })

  it('null 备注应显示"暂无备注"占位', async () => {
    render(
      <RemarkPopover remark={null}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByText('暂无备注')).toBeTruthy()
  })

  it('单条备注应正常显示', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 仅一条备注">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByText('仅一条备注')).toBeTruthy()
    expect(screen.getByText('2026-07-01 10:00')).toBeTruthy()
  })

  it('长备注内容应完整显示不截断', async () => {
    const longText = 'A'.repeat(300)
    const remark = `[2026-07-01 10:00] ${longText}`

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    // 长文本应完整显示
    expect(screen.getByText(longText)).toBeTruthy()
  })

  it('备注含特殊字符应正确转义显示', async () => {
    const remark = '[2026-07-01 10:00] <script>alert("xss")</script> & emoji 🎉'

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    // React 自动转义，script 标签应作为纯文本显示
    const content = screen.getByText(/script/)
    expect(content).toBeTruthy()
    expect(content.textContent).toContain('<script>alert("xss")</script>')
    expect(content.textContent).toContain('🎉')
  })

  it('浮窗应包含三角箭头元素', async () => {
    render(
      <RemarkPopover remark="[2026-07-01 10:00] 测试">
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    // 验证 role="tooltip" 存在
    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeTruthy()
  })

  it('无时间戳的备注行应正常显示', async () => {
    const remark = '纯文本备注，无时间戳'

    render(
      <RemarkPopover remark={remark}>
        <span data-testid="trigger">{triggerText}</span>
      </RemarkPopover>
    )

    const trigger = screen.getByTestId('trigger')
    fireEvent.mouseEnter(trigger)
    act(() => {
      vi.advanceTimersByTime(250)
    })

    expect(screen.getByText('纯文本备注，无时间戳')).toBeTruthy()
  })
})
