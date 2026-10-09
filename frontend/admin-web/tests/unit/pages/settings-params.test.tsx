// case_ids: UI-054
/**
 * 旧链 `/settings/params` = **重定向**守卫（issue #6580）。
 *
 * ## 这一页还剩什么
 *
 * 它曾经是「参数总览」一级菜单项的第一屏（issue #6573）。用户 2026-10-09 裁定把
 * **加工项管理 / 工艺配置 / 参数总览全部收拢进「企业基础设置」** ⇒ 本页面的内容并回
 * `/settings` 的「算料口径」域，本文件判的就只剩**迁移契约**这一件事：
 *
 * 1. 旧深链**不 404**：渲染即 `router.replace('/settings?domain=calc')`（仓内「旧路径保留为重定向」口径）；
 * 2. 🔴 **不许再发任何读面**：`/settings/params` 与 `/settings` 编辑的是**同一份配置**
 *    （`production/craft-calc-config`）—— 若这里再挂一个取数/编辑面，就是设计真值源
 *    （`docs/design/enterprise-settings-redesign.md`）写死的**判死线第 1 条**：
 *    「同一配置不许两个入口」，也正是用户说的「散乱的配置乱放」。
 *
 * 判据 1 的行为面 + 判据 2 的源码面是**两条独立断言**（行为对了但源码里藏着取数 = 仍然红）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const replace = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }))

import SettingsParamsRedirect from '@/app/(dashboard)/settings/params/page'

const PAGE_SRC = resolve(__dirname, '../../../src/app/(dashboard)/settings/params/page.tsx')

describe('判据 5：旧链 `/settings/params` 只做跳转（不渲染任何配置面）', () => {
  beforeEach(() => {
    replace.mockClear()
  })

  it('渲染 ⇒ 重定向到「企业基础设置」的「算料口径」域（旧深链不 404）', async () => {
    const { container } = render(<SettingsParamsRedirect />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/settings?domain=calc'))
    // 恰好一次（跳两次 = 闪烁 + 可被读成两个入口）
    expect(replace).toHaveBeenCalledTimes(1)
    // 自己不渲染任何东西（没有表单、没有就绪度、没有任何面板）
    expect(container.firstChild).toBeNull()
  })

  it('🔴 判别力：本页源码**不得**再出现任何取数（同一份配置两个入口 = 判死线第 1 条）', () => {
    const src = readFileSync(PAGE_SRC, 'utf8')
    expect(src).not.toMatch(/@\/lib\/api/)
    expect(src).not.toMatch(/useEffect\([^)]*productionApi/)
    expect(src).toMatch(/router\.replace\('\/settings\?domain=calc'\)/)
  })
})
