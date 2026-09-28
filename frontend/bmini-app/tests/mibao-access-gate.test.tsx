// case_ids: BM-008
/**
 * 米宝唤出授权门（bmini-app 侧，issue #5642 功能⑤）。
 *
 * ## 病灶（本包要治的形态）
 * 改动前「人人可唤米宝」—— `pages/chat` **零权限门**（设计单 §1.1 读数⑤）。
 * 用户 2026-09-26 裁定：「管理员可以在 H5 上唤出 migao Agent 进行对话，
 * **其他员工需要授权**才能唤出」⇒ 未授权者必须看到**明确的授权缺失态**，
 * 而不是静默隐藏入口（违反要求）或 403 白屏（违反要求）。
 *
 * ## 本文件锁五条（每条能红）
 * ① allowed=true ⇒ 渲染米宝对话内容；
 * ② allowed=false ⇒ 拒绝态**渲染出来了**（入口可见，非静默隐藏）+ 逐字「需要管理员授权」+ 可行动引导；
 * ③ allowed=false ⇒ 不是 403 白屏（无 403 字样、有可读引导）；
 * ④ allowed=null ⇒ 不渲染任何一侧（判定未回来时不得误报「没权限」）；
 * ⑤ 前端零权限码 —— 组件与页面**只**消费服务端下发的 `capabilities.mibaoChat`。
 *
 * ⚠️ h5 与 weapp 是**同一份代码的两种编译产物**（`frontend/bmini-app` 一端双编译）
 * ⇒ 本判据在两种产物里同时生效，不需要第二份实现（设计单 §6.1）。
 * ⚠️ 断言形态用本包的既有口径（`toBeTruthy()` / `toBeNull()`）—— 本包未接
 * `@testing-library/jest-dom`，用它会让整个 suite 编译不过（实测踩过）。
 */
import React from 'react'
import { render, screen } from '@testing-library/react'

import MibaoAccessGate, {
  MIBAO_NEEDS_ADMIN_GRANT_TEXT,
  MIBAO_GRANT_GUIDE_TEXT,
} from '../src/components/chat/MibaoAccessGate'

describe('米宝唤出授权门（bmini）', () => {
  it('① allowed=true ⇒ 渲染米宝对话内容', () => {
    render(
      <MibaoAccessGate allowed={true}>
        <div data-testid='mibao-content'>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(screen.getByTestId('mibao-content')).toBeTruthy()
    expect(screen.queryByTestId('mibao-gate-denied')).toBeNull()
  })

  it('② allowed=false ⇒ 入口可见 + 逐字「需要管理员授权」+ 可行动引导', () => {
    render(
      <MibaoAccessGate allowed={false}>
        <div data-testid='mibao-content'>米宝对话</div>
      </MibaoAccessGate>,
    )
    // 拒绝态渲染出来了 ⇒ 入口可见（不是静默隐藏）
    expect(screen.getByTestId('mibao-gate-denied')).toBeTruthy()
    // 逐字文案（改字即红）—— 判据 G3
    expect(MIBAO_NEEDS_ADMIN_GRANT_TEXT).toBe('需要管理员授权')
    expect(screen.getByText(MIBAO_NEEDS_ADMIN_GRANT_TEXT)).toBeTruthy()
    expect(screen.getByText(MIBAO_GRANT_GUIDE_TEXT)).toBeTruthy()
    expect(screen.getByText(/员工管理/)).toBeTruthy()
    expect(screen.queryByTestId('mibao-content')).toBeNull()
  })

  it('③ allowed=false ⇒ 不是 403 白屏', () => {
    const { container } = render(
      <MibaoAccessGate allowed={false}>
        <div>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(container.textContent || '').not.toMatch(/403/)
    expect(container.textContent || '').toContain(MIBAO_NEEDS_ADMIN_GRANT_TEXT)
    expect(container.textContent || '').toContain(MIBAO_GRANT_GUIDE_TEXT)
  })

  it('④ allowed=null ⇒ 不渲染任何一侧（判定未回来）', () => {
    const { container } = render(
      <MibaoAccessGate allowed={null}>
        <div>米宝对话</div>
      </MibaoAccessGate>,
    )
    expect(container.textContent || '').toBe('')
  })

  it('⑤ 前端零权限码：组件与对话页都只读服务端能力位，不判任何权限码', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const gateSrc = fs.readFileSync(
      path.resolve(__dirname, '../src/components/chat/MibaoAccessGate.tsx'),
      'utf8',
    )
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, '../src/pages/chat/index/index.tsx'),
      'utf8',
    )
    // 形态 = 「带冒号的 resource:action 字面量」
    expect(gateSrc).not.toMatch(/['"`][a-z_]+:[a-z_]+['"`]/)
    expect(pageSrc).not.toMatch(/['"`][a-z_]+:[a-z_]+['"`]/)
    // 两端都从服务端下发的布尔位取值
    expect(gateSrc).toContain('mibaoChat')
    expect(pageSrc).toContain('capabilities?.mibaoChat')
    // 对话页必须挂上这道门（去掉 ⇒ 红）
    expect(pageSrc).toContain('MibaoAccessGate')
  })
})
