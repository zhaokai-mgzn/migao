'use client'

/**
 * `performance.measure` 区间守卫的**客户端接线点**（issue #6946）。
 *
 * ## 为什么要单独一个 `'use client'` 模块（这是 #6799 ② 漏掉的那一环）
 * 旧接法是 `src/app/layout.tsx` 里一句 `import '../lib/user-timing-guard'`。但 **`layout.tsx` 没有 `'use client'`
 * ⇒ 它是 Server Component ⇒ 那句 import 只在 Node 侧执行**，而守卫入口有 `typeof window === 'undefined'` 短路
 * ⇒ **空操作**：浏览器里 `performance.measure` 始终是原生的。
 * 真栈实测（2026-10-15，Playwright）：`performance.measure.__userTimingGuardInstalled === false`、
 * `String(performance.measure).includes('[native code]') === true` —— 而当时的接线判据（静态查 layout 里那行 import）**照样绿**。
 * ⇒ 「有一个好用的守卫」≠「守卫被装上」；判据必须落在**客户端能不能真装上**这条链上。
 *
 * 本模块带 `'use client'` ⇒ 随客户端 bundle 加载，**模块顶层**代码在 React 首次渲染之前执行（不是 `useEffect` —— 那时首次
 * commit 的埋点已经跑过了）。`installUserTimingGuard()` 幂等，重复调用无害。
 */
import { installUserTimingGuard } from '@/lib/user-timing-guard'

installUserTimingGuard()

export default function UserTimingGuard() {
  return null
}
