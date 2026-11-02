'use client'

/**
 * 官网 / 企业站路由组错误边界（issue #8203 · P0-03）。
 *
 * `(corporate)` 是**未登录**访客（含搜索引擎）能看到的那一面：白屏的代价比工作台更高
 * （访客没有任何「换个入口再试」的路径）。回入口取站点根 `/`。
 */
import ErrorFallback from '@/components/common/ErrorFallback'

export default function CorporateError({
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
      description="这一页暂时没能加载出来。可以点「重试」；仍然不行就回到首页。"
      homeHref="/"
      homeLabel="回到首页"
    />
  )
}
