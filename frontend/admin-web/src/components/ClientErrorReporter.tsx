'use client'

/**
 * 全局错误上报的**客户端接线点**（issue #8203 · P0-03）。
 *
 * ## 为什么是 `'use client'` 模块 + 模块顶层安装
 * `src/app/layout.tsx` 是 Server Component ⇒ 在那里 `import` 一个只在浏览器里有效的守卫，
 * 只会被执行在 Node 侧（同族实测见 `src/components/UserTimingGuard.tsx` 的文件头，issue #6946）。
 * 本模块带 `'use client'` ⇒ 随客户端 bundle 加载，**模块顶层**代码在 React 首次 commit 之前执行 ——
 * 那正是要覆盖的窗口：hydration 期崩溃（hydration mismatch / 首屏数据形状变化）也必须被上报。
 *
 * 幂等：`installClientErrorHandlers()` 自带安装标记，React 重挂组件不会叠加监听。
 */
import { useEffect } from 'react'
import { installClientErrorHandlers } from '@/lib/clientErrorReporter'

// 模块顶层：早于任何组件渲染（SSR 侧自动短路）
installClientErrorHandlers()

export default function ClientErrorReporter() {
  useEffect(() => {
    // 兜底再装一次：模块顶层在纯 SSR 时是空操作，客户端 hydrate 后这里确保装上（幂等 ⇒ 不会重复）
    installClientErrorHandlers()
  }, [])
  return null
}
