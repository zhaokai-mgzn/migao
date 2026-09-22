import { useSyncExternalStore } from 'react'

/**
 * useNow — 当前时间（毫秒），按固定间隔推进。
 *
 * 为什么需要它：组件在**渲染期**读 `Date.now()` 是不纯的（同一 props/state 会算出不同结果），
 * 且一旦被 `useMemo` 缓存住，**无 `updated_at` 的会话历时会永远停在挂载那一刻**（真缺陷）。
 * 这里把「当前时间」做成渲染期可安全读取的**外部快照**：
 *   · `getSnapshot` 只在 store 的 interval 里推进（渲染期只读缓存值，不调用 `Date.now()`）；
 *   · 快照值稳定 ⇒ 不触发无谓重渲，只在时间真正推进时重渲一次。
 */
const TICK_MS = 30_000

let current = Date.now()
const listeners = new Set<() => void>()

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange)
  if (listeners.size === 1) {
    current = Date.now()
    timer = setInterval(() => {
      current = Date.now()
      listeners.forEach((l) => l())
    }, TICK_MS)
  }
  return () => {
    listeners.delete(onStoreChange)
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }
}

let timer: ReturnType<typeof setInterval> | null = null

const getSnapshot = () => current

/** 服务端/首帧快照：直接取当前时间（只在 SSR 渲染路径上调用，不进 effect 生命周期）。 */
const getServerSnapshot = () => Date.now()

export function useNow(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
