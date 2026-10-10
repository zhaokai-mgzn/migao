'use client'

import { AlertTriangle } from 'lucide-react'

interface ListLoadErrorProps {
  /**
   * 失败态锚点（`data-testid`）—— 沿用既有命名规范 `<页面>-load-error`
   * （如 `orders-load-error` / `finance-load-error`）。重试出口取 `${testId}-retry`。
   */
  testId: string
  /** 说清「不是没有数据，是读不到」——由调用方给本页面的读对象名 */
  message: string
  onRetry: () => void
  retrying?: boolean
}

/**
 * 列表读面失败的**常驻**出口（issue #6703）。
 *
 * 为什么要有共享件：同一形态（`AlertTriangle` + 「读不到」+ 重试）在
 * `/roles`（`roles-load-error`，issue #6663）已经立过范式；本单要把它补到
 * `/orders` `/finance` `/customers` `/after-sales` `/knowledge` 五页 ——
 * 复制五份就是第二份会漂的口径（铁律 5 最少代码阶梯：先复用 / 抽公共件）。
 *
 * 为什么必须**常驻**（而不是只靠 toast）：`lib/request.ts` 拦截器播的 toast
 * **约 4s 后消失**，商家回到屏幕只剩列表（以及被读坏的计数行）——
 * 「读面故障不得画成空态」(#6691) 的那条纪律对**计数行**同样成立。
 */
export default function ListLoadError({ testId, message, onRetry, retrying = false }: ListLoadErrorProps) {
  return (
    <div
      data-testid={testId}
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 mb-4 text-sm text-red-700"
    >
      <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
      <span className="flex-1">{message}</span>
      <button
        type="button"
        data-testid={`${testId}-retry`}
        onClick={onRetry}
        disabled={retrying}
        className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
      >
        重新加载
      </button>
    </div>
  )
}
