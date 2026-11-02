'use client'

/**
 * 工作台路由组错误边界（issue #8203 · P0-03）。
 *
 * 改前本仓 58 个页面里只有 `(dashboard)/customers/error.tsx` **一个**错误边界 ⇒ 其余页面的
 * 渲染期异常全部落到 Next.js 默认错误页（整页白屏 + 无重试出口，审计 P0-03）。
 * 本文件把出口提到**路由组**一层：组内任何页面（含未来新增的）自动获得「重试 + 回工作台 + 上报」，
 * 不需要每加一页就记得复制一份。
 *
 * 与 `customers/error.tsx` 的关系：更具体的那一个优先（Next.js 就近原则），它保持原样、同形态。
 */
import ErrorFallback from '@/components/common/ErrorFallback'

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="页面加载出错"
      description="这一页暂时没能加载出来，错误已经记录。可以点「重试」；仍然不行就回工作台继续操作。"
      homeHref="/dashboard"
      homeLabel="回到工作台"
    />
  )
}
