// case_ids: UI-024
/**
 * lucide-react 的 mock 工厂（研发工具，issue #6664）。
 *
 * 逐个列出图标名（`Search: stub(...)`）会在**任一被导入的 UI 组件新增图标**时炸
 * 「No "X" export is defined on the "lucide-react" mock」—— 那是 mock 维护问题，
 * 不是被测行为，而且它把「测试挂了」和「代码坏了」混在一起。
 *
 * 实现取「**真实模块 + 局部覆盖**」：`importOriginal()` 拿到真 lucide-react，
 * 再对被测 UI 会 import 的图标名覆盖成轻量 stub。真模块里其余导出原样保留
 * ⇒ 测试环境不依赖「恰好列全了图标名」这个脆弱前提。
 *
 * ❌ **不要**写成「对任意 key 返回组件」的裸 Proxy：`import * as X` 取 `then`
 * （vitest 判 thenable）/ `Symbol.toStringTag` 时也会拿到函数 ⇒ 模块被当成永远 pending 的
 * Promise，**整个 vitest run 挂死**（本包实测踩过）。
 *
 * 用法（`vi.mock` 工厂会被提升，故必须 `await import` 本模块，不能用外部变量）：
 * ```ts
 * vi.mock('lucide-react', async (importOriginal) =>
 *   (await import('../helpers/lucide-mock')).lucideMock(await importOriginal()))
 * ```
 */
import { createElement, type ComponentType } from 'react'

/** 被测 UI（`@/components/ui/**`、页面、模态框）会 import 的图标名 —— 未列到的仍可用真图标 */
const STUB_ICONS = [
  // EmptyState / 通用空态
  'Package', 'Search', 'FileX', 'Inbox', 'AlertTriangle',
  // 导航 / 分页
  'ChevronLeft', 'ChevronRight', 'ChevronUp', 'ChevronDown', 'ChevronsLeft', 'ChevronsRight',
  // 动作
  'Plus', 'X', 'Trash2', 'Eye', 'RefreshCw', 'RotateCcw', 'Printer', 'Copy', 'Download',
  'Calendar', 'FileText', 'ExternalLink', 'Filter', 'Edit', 'Pencil', 'Check', 'CheckCircle',
] as const

export function lucideMock(
  actual: Record<string, unknown> = {},
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...actual }
  for (const name of STUB_ICONS) {
    const testId = `icon-${name.toLowerCase()}`
    const stub: ComponentType<Record<string, unknown>> = (props) =>
      createElement('span', { 'data-testid': testId, ...props })
    out[name] = stub
  }
  return out
}
