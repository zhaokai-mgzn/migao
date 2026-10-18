// case_ids: UI-054, UI-123
/**
 * 旧「工艺配置」路由 `/production/routings` —— **已下架，只许重定向**（issue #7182 改判；原判据见 issue #6825）。
 *
 * ## 沿革（为什么这条判据从「tab=calc 重定向」变成「整条路由重定向」）
 *
 * - issue #6825：算料配置的写面收敛进 `/settings?domain=calc`，旧深链 `?tab=calc` 改成重定向；
 *   其余形态（无 tab / `tab=process` / `tab=cut`）**仍渲染本页功能体**。
 * - issue #7182（2026-10-18 用户报障「原工艺配置页面怎么未下架」）：功能体已全部内嵌在
 *   企业基础设置（`operation-prices` / `cutting-height` / `craft-route`），这条路由成了**第二个写面**
 *   ⇒ 整条路由改成重定向到 `/settings?domain=operation-prices`，**不再渲染任何东西**。
 *
 * ## 判据
 *
 * 1. 渲染即 `router.replace('/settings?domain=operation-prices')`，**恰好一次**，容器为空；
 * 2. 用 `replace` 而不是 `push`（旧链不进浏览历史）；
 * 3. 源码面：本页**不再** import `ProcessConfigBoard`（不挂第二个写面）。
 */
import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const replace = vi.fn()
const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/production/routings',
}))

import LegacyRoutingsPage from '@/app/(dashboard)/production/routings/page'

const PAGE_SRC = resolve(__dirname, '../../../src/app/(dashboard)/production/routings/page.tsx')
const SETTINGS_HREF = '/settings?domain=operation-prices'

describe('旧「工艺配置」路由已下架（issue #7182）', () => {
  beforeEach(() => {
    replace.mockClear()
    push.mockClear()
  })

  it('渲染即 replace 到唯一写面，恰好一次，且不渲染任何功能体', async () => {
    const { container } = render(<LegacyRoutingsPage />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith(SETTINGS_HREF))
    expect(replace).toHaveBeenCalledTimes(1)
    expect(push, '旧链不该留在浏览历史里').not.toHaveBeenCalled()
    expect(container).toBeEmptyDOMElement()
  })

  it('源码面：本页不再 import 功能体（不挂第二个写面）', () => {
    // 只看**代码**（注释里必须允许写「改前渲染 ProcessConfigBoard」——那是下架说明）
    const code = readFileSync(PAGE_SRC, 'utf-8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    expect(code).not.toContain('ProcessConfigBoard')
    expect(code).toContain(SETTINGS_HREF)
  })
})
