// case_ids: OR-001, UI-048
/**
 * 备注浮层的**可达性**（issue #6664 第 8 条）。
 *
 * 改前（缺陷形态）：触发元素只有 `onMouseEnter` ⇒ **触屏（点不动）/ 键盘（Tab 到不了、回车没反应）**
 * 读不到备注。而平板试用是常态（用户裁定「按顶尖互联网设计规范做基线」）。
 * 判据：聚焦 / 点击 / Enter / Space 都能开，Esc 能收；鼠标悬停这条**旧路径不许回退**。
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import RemarkPopover from '@/components/orders/RemarkPopover'

vi.mock('react-dom', async () => {
  const actual = await vi.importActual('react-dom')
  return {
    ...actual,
    createPortal: (children: React.ReactNode) => children,
  }
})

function renderPopover() {
  render(
    <RemarkPopover remarks={[{ id: 'r1', content: '客户要求加急', operator: '小王', createdAt: '2026-01-01T02:00:00Z' }] as any}>
      <span>备注入口</span>
    </RemarkPopover>,
  )
  inspectTrigger()
}

function inspectTrigger() {
  // 触发元素 = 备注入口的祖先（role=button）
  return screen.getByRole('button', { name: /备注入口/ })
}

describe('RemarkPopover 可达性（issue #6664 第 8 条）', () => {
  it('① 鼠标悬停仍能打开（旧路径不回退）', () => {
    renderPopover()
    expect(screen.queryByText('客户要求加急')).toBeNull()
    fireEvent.mouseEnter(inspectTrigger())
    expect(screen.getByText('客户要求加急')).toBeInTheDocument()
  })

  it('② **聚焦**（键盘 Tab 到）就能打开 —— 触屏/键盘用户读得到', () => {
    renderPopover()
    const trigger = inspectTrigger()
    expect(trigger).toHaveAttribute('tabindex', '0')
    fireEvent.focus(trigger)
    expect(screen.getByText('客户要求加急')).toBeInTheDocument()
  })

  it('③ **点击**就能打开（平板点按 = 常态）', () => {
    renderPopover()
    fireEvent.click(inspectTrigger())
    expect(screen.getByText('客户要求加急')).toBeInTheDocument()
  })

  it('④ Enter / Space 能开、Esc 能收（键盘闭环）', () => {
    renderPopover()
    const trigger = inspectTrigger()
    fireEvent.keyDown(trigger, { key: 'Enter' })
    expect(screen.getByText('客户要求加急')).toBeInTheDocument()
    fireEvent.keyDown(trigger, { key: 'Escape' })
    expect(screen.queryByText('客户要求加急')).toBeNull()
  })

  it('⑤ 展开状态对辅助技术可见（aria-expanded 随开合变化）', () => {
    renderPopover()
    const trigger = inspectTrigger()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
