'use client'

/**
 * 客户管理页错误边界（issue #8203 之前就存在的那一个 —— 本仓**唯一**的错误出口）。
 *
 * issue #8203 把它收敛到共享形态 `ErrorFallback`：页面级文案保持（客户管理页），但
 * 「重试 + 回工作台 + 上报一次」的行为与其余路由组**同源**，不再各写一份。
 * （Next.js 就近原则：本文件对 `/customers/**` 优先于 `(dashboard)/error.tsx`。）
 */
import ErrorFallback from '@/components/common/ErrorFallback'

export default function CustomersError({
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
      title="客户管理页加载出错"
      description="客户数据暂时没能加载出来，错误已经记录。可以点「重试」；仍然不行就回工作台稍后再进。"
      homeHref="/dashboard"
      homeLabel="回到工作台"
    />
  )
}
