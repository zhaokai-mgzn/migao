'use client'

/**
 * 根级错误边界（issue #8203 · P0-03）。
 *
 * `app/global-error.tsx` 是 Next.js **最后一道**客户端边界：它接住 **root layout 自身**的渲染异常
 * （这类异常不会被任何 `app/error.tsx` 接住）。改前本仓**没有**这个文件 ⇒ root layout 一崩就是
 * 浏览器默认白屏（无出口、无上报）。
 *
 * ⚠️ 两个 Next.js 约束（写错了文件等于没写）：
 * 1. 必须自带 `<html>` / `<body>` —— 本组件**替换**整个 root layout（`globals.css` 仍由构建注入）；
 * 2. 必须是**客户端组件**（`'use client'`），且 `reset` 由 Next 注入。
 *
 * 已知不覆盖（照实登记）：`global-error` 只在**生产构建**里生效；开发态的 overlay 会盖住它
 * ⇒ 验收要以 `npm run build && npm run start`（或线上）为准，`npm run dev` 里看不见它。
 */
import ErrorFallback from '@/components/common/ErrorFallback'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="zh-CN">
      <body>
        <ErrorFallback
          error={error}
          reset={reset}
          title="观星台暂时无法加载"
          description="页面渲染出现异常，已经记录。可以点「重试」重新加载；仍然不行就回首页重新进入。"
          homeHref="/"
          homeLabel="回到首页"
        />
      </body>
    </html>
  )
}
