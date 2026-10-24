// case_ids: UI-123
/**
 * 旧「工艺配置」路由已下架（issue #7182）。
 *
 * 用户报障（2026-10-18）：「原工艺配置页面怎么未下架，从计件工资提示链接可以跳转到原页面，
 * 这里应该跳转到新页面了」。改前：`/production/routings` 是仍可渲染的**第二写面**，
 * 且计件工资的「去定价」链接指向它。
 *
 * 判据：
 * 1. 渲染旧路由 ⇒ `router.replace('/settings?domain=operation-prices')`，且**不渲染任何内容**；
 * 2. 全仓 `src/` 里不再有指向 `/production/routings` 的 `href`（只许剩重定向与注释）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const replace = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

import LegacyRoutingsPage from '@/app/(dashboard)/production/routings/page'

const SRC = join(process.cwd(), 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/**
 * 只看**能跳过去的写法**：`href=` / `redirect(` / `router.push|replace(` **同一行里带字面路径**。
 *
 * 口径（别把判据放大成「全文里出现这串字符就红」）：
 * - `page-context.ts` 的路由→上下文映射、`layout.tsx` 的权限前缀都不是链接 ⇒ 读成违规只是假红（§25）；
 * - 走常量的链接（如 `href={PRICING_ENTRY_HREF}`）不在此射程内 —— 那是上一条实例判据的活
 *   （`UnpricedNotice.test.tsx` 钉住常量的值），本判据只管**写死的字面链接**；
 * - 注释里允许保留历史路径 —— 那正是下架说明。
 */
function linksToRetiredRoute(): string[] {
  const hits: string[] = []
  for (const file of walk(SRC)) {
    const code = readFileSync(file, 'utf-8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '')
    for (const line of code.split('\n')) {
      if (!line.includes('/production/routings')) continue
      if (/\bhref\s*=/.test(line) || /\bredirect\s*\(/.test(line) || /router\.(push|replace)\s*\(/.test(line)) {
        hits.push(`${file.replace(`${SRC}/`, 'src/')}: ${line.trim()}`)
        break
      }
    }
  }
  return hits
}

describe('旧「工艺配置」路由下架（issue #7182）', () => {
  beforeEach(() => replace.mockClear())

  it('渲染即 replace 到唯一写面，且不再渲染板子', async () => {
    const { container } = render(<LegacyRoutingsPage />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/settings?domain=operation-prices'))
    expect(container).toBeEmptyDOMElement()
  })

  it('全仓不再有代码指向旧路由（注释里的历史说明不算）', () => {
    expect(linksToRetiredRoute()).toEqual([])
  })
})
