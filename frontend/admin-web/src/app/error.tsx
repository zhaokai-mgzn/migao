'use client'

/**
 * app 级错误边界（issue #8203 · P0-03）。
 *
 * 覆盖**没有自己 `error.tsx`** 的路由：登录 / 注册 / 改密（`login/`、`register/`、`change-password/`
 * 三个目录，本仓**没有** `(auth)` 路由组）以及**路由组 layout 自身**抛出的异常
 * （`(dashboard)/layout.tsx` 崩了不会被 `(dashboard)/error.tsx` 接住 —— 那是它的父边界）。
 *
 * 回入口取 `/login`：本边界可能正是被「工作台 layout 崩了」触发的，回 `/dashboard` 会立刻再崩一次；
 * 登录页是静态页，是最可靠的出口。
 */
import ErrorFallback from '@/components/common/ErrorFallback'

export default function AppError({
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
      description="这一页暂时没能加载出来，错误已经记录。可以点「重试」；仍然不行就回登录页重新进入。"
      homeHref="/login"
      homeLabel="回到登录页"
    />
  )
}
