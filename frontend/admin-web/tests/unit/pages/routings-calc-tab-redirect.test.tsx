// case_ids: UI-054
/**
 * 旧深链 `?tab=calc` ⇒ 新写面的**重定向守卫**（issue #6825）。
 *
 * ## 为什么必须重定向（而不是 404 / 落空白）
 *
 * 板子的「算料配置」tab 是算料配置的**第二个写面**（与「企业基础设置」的「算料口径」域同一份配置
 * `GET/PUT /api/admin/production/craft-calc-config`）—— 设计真值源
 * `docs/design/enterprise-settings-redesign.md` 判死线第 1 条明文禁止。issue #6825 把唯一写面收敛进
 * `/settings?domain=calc`（8 标量 + 档位 + 拼色 + 公式 + **一个**保存按钮），于是：
 *
 * 1. **旧深链不许 404 / 落空白**（仓内口径「旧链保留」；下单页「参数说明」与老书签都指向过它）⇒
 *    `router.replace('/settings?domain=calc')`，**恰好一次**（跳两次 = 闪烁 + 可被读成两个入口）；
 * 2. **其余形态行为一字不变**：无 `tab` / `tab=process` / `tab=cut` 仍渲染本页功能体
 *    （`/production/routings` 保留为薄壳，理由见设计 §6 债务第 4 条）。
 *
 * 判据是**两条独立断言**：行为面（跳没跳、跳到哪）+ 源码面（本页不得再挂第二个写面）。
 */
import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const replace = vi.fn()
const push = vi.fn()
const searchParams = vi.fn(() => new URLSearchParams())
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push }),
  useSearchParams: () => searchParams(),
  usePathname: () => '/production/routings',
}))
// 本文件只判**路由层**（跳转与源码）；功能体整体替身掉（它的判据在 production-routings.test.tsx）
vi.mock('@/components/production-config/ProcessConfigBoard', () => ({
  default: () => createElement('div', { 'data-testid': 'stub-process-config-board' }),
}))

import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

const PAGE_SRC = resolve(__dirname, '../../../src/app/(dashboard)/production/routings/page.tsx')

describe('判据 5：`?tab=calc` 旧深链 ⇒ 落到新写面（不 404、不落空白）', () => {
  beforeEach(() => {
    replace.mockClear()
    push.mockClear()
    searchParams.mockReturnValue(new URLSearchParams())
  })

  it('tab=calc 深链 ⇒ router.replace 到 /settings?domain=calc，恰好一次，且本页不渲染任何写面', async () => {
    searchParams.mockReturnValue(new URLSearchParams('tab=calc'))
    const { container } = render(<ProcessConfigPage />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/settings?domain=calc'))
    // 恰好一次（跳两次 = 闪烁 + 可被读成两个入口）
    expect(replace).toHaveBeenCalledTimes(1)
    // 用 `replace` 而不是 `push`：旧链不该留在浏览历史里（回退会弹回一个已退役的 tab）
    expect(push).not.toHaveBeenCalled()
    // 自己不渲染功能体（更不渲染算料写面）
    expect(container.querySelector('[data-testid="stub-process-config-board"]')).toBeNull()
  })

  it('对照读数：无 tab / tab=process / tab=cut ⇒ 照旧渲染功能体，一次都不跳', async () => {
    for (const search of ['', 'tab=process', 'tab=cut']) {
      searchParams.mockReturnValue(new URLSearchParams(search))
      const { unmount, findByTestId } = render(<ProcessConfigPage />)
      expect(await findByTestId('stub-process-config-board')).toBeInTheDocument()
      expect(replace, `search=「${search}」不该发生跳转`).not.toHaveBeenCalled()
      unmount()
    }
  })
})

describe('判据 5b：本页源码里**不再有**第二个算料写面', () => {
  it('路由页不得挂载算料写面（craft-calc-config-* / CalcFormulaPanel）', () => {
    const src = readFileSync(PAGE_SRC, 'utf8')
    // 自证非空（空文件上的「不含 X」恒真）
    expect(src).toContain('ProcessConfigBoard')
    expect(src).not.toMatch(/CalcFormulaPanel/)
    expect(src).not.toMatch(/calc-caliber/)
    expect(src).not.toMatch(/craft-calc-config-(panel|save|scalar|default_formula)/)
  })
})
