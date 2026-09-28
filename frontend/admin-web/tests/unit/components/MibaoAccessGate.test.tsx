// case_ids: BM-008
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import MibaoAccessGate, {
  MIBAO_NEEDS_ADMIN_GRANT_TEXT,
  MIBAO_GRANT_GUIDE_TEXT,
} from '@/components/business/MibaoAccessGate'

/**
 * 米宝唤出授权门（admin-web 侧，issue #5642 功能⑤）。
 *
 * 判据（设计单 §8.5 G2~G4）：
 * ① 可唤 ⇒ 渲染米宝对话内容；
 * ② 不可唤 ⇒ **入口可见**（不是静默隐藏）+ 逐字「需要管理员授权」+ **可行动引导**；
 * ③ 不可唤 ⇒ **不是 403 白屏**（无 403 字样、组件是正常渲染出来的引导视图）；
 * ④ 判定未回来（null/undefined）⇒ 不渲染拒绝态（不把「还没拿到」误报成「没权限」）；
 * ⑤ 前端零权限码（源码里不出现任何权限码字面量）。
 */
describe('MibaoAccessGate（米宝唤出授权门）', () => {
  it('① allowed=true ⇒ 渲染米宝对话内容', () => {
    render(
      <MibaoAccessGate allowed={true}>
        <div data-testid='mibao-content'>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(screen.getByTestId('mibao-content')).toBeInTheDocument()
    expect(screen.queryByTestId('mibao-gate-denied')).not.toBeInTheDocument()
  })

  it('② allowed=false ⇒ 入口可见 + 逐字「需要管理员授权」+ 可行动引导', () => {
    render(
      <MibaoAccessGate allowed={false}>
        <div data-testid='mibao-content'>米宝对话</div>
      </MibaoAccessGate>,
    )
    // 拒绝态**渲染出来了**（= 入口可见，不是静默隐藏）
    expect(screen.getByTestId('mibao-gate-denied')).toBeInTheDocument()
    // 逐字文案（改字即红）
    expect(screen.getByText(MIBAO_NEEDS_ADMIN_GRANT_TEXT)).toBeInTheDocument()
    expect(MIBAO_NEEDS_ADMIN_GRANT_TEXT).toBe('需要管理员授权')
    // 可行动引导（去哪授权 / 找谁）
    expect(screen.getByText(MIBAO_GRANT_GUIDE_TEXT)).toBeInTheDocument()
    expect(screen.getByText(/员工管理/)).toBeInTheDocument()
    // 拒绝对话内容本身
    expect(screen.queryByTestId('mibao-content')).not.toBeInTheDocument()
  })

  it('③ allowed=false ⇒ 不是 403 白屏（无 403 字样、有可读引导）', () => {
    const { container } = render(
      <MibaoAccessGate allowed={false}>
        <div>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(container.textContent || '').not.toMatch(/403/)
    expect(container.textContent || '').toContain(MIBAO_NEEDS_ADMIN_GRANT_TEXT)
    expect(container.textContent || '').toContain(MIBAO_GRANT_GUIDE_TEXT)
  })

  it('④ allowed 为 null/undefined ⇒ 不渲染任何一侧（判定未回来）', () => {
    const a = render(
      <MibaoAccessGate allowed={null}>
        <div>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(a.container.textContent || '').toBe('')
    const b = render(
      <MibaoAccessGate allowed={undefined}>
        <div>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(b.container.textContent || '').toBe('')
  })

  it('⑤ 前端零权限码：源码里没有任何权限码字面量（只消费服务端能力位）', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../../src/components/business/MibaoAccessGate.tsx'),
      'utf8',
    )
    // 形态 = 「带冒号的 resource:action 字面量」；本组件只读 capabilities.mibaoChat
    expect(src).not.toMatch(/['"`][a-z_]+:[a-z_]+['"`]/)
    expect(src).toContain('mibaoChat')
  })
})
