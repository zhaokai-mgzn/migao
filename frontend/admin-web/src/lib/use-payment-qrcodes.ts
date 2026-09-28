'use client'

import { useEffect, useState } from 'react'
import { settingsApi } from '@/lib/api'
import type { PaymentQrcodeMap } from '@/types'

/**
 * 收款码读取口（**单一实现**，issue #5651 抽取）—— 报价单（#4965）与销售单（#5651）
 * 的「扫码支付」块共用这一份。抽出来的理由与 `lib/order-amount.ts` 同因：
 * **同一件事实在两处各写一次 ⇒ 将来改一处、另一处静默不一致**，而纸面不一致 =
 * 客户扫了打不开的码。
 *
 * 口径（勿改，两条都有实测理由）：
 * 1. **调用方给了 `provided` ⇒ 一律用它**（调用方 / 测试注入优先）。
 * 2. 没给 ⇒ **在打印时**取（`beforeprint`）：本组件在订单详情页**常驻挂载**
 *    （屏幕态 `display:none`），挂载即拉会在每次打开详情页都发一次请求，而绝大多数
 *    打开并不打印；`window.print()` 一定会触发 `beforeprint`，正好是「要纸面了」的时刻。
 * 3. **失败 / 为空 / 无权限一律按「无码」**（返回 `{}`，不抛不弹 toast）——
 *    调用方据此**整块不出现**：🔴 **缺码不画假码**（#4965 / 洗水码同一条判据）。
 *    `/api/admin/settings/payment-qrcodes` 需 `system:manage` 权限 ⇒ 无权限账号走到
 *    这里必然失败，属预期而非错误。
 */
export function usePaymentQrcodes(provided?: PaymentQrcodeMap): PaymentQrcodeMap {
  const [fetched, setFetched] = useState<PaymentQrcodeMap | null>(null)

  useEffect(() => {
    if (provided !== undefined) return
    let cancelled = false
    const load = () => {
      try {
        settingsApi
          .getPaymentQrcodes()
          .then((res) => {
            if (!cancelled) setFetched(res?.data?.data ?? {})
          })
          .catch(() => {
            if (!cancelled) setFetched({})
          })
      } catch {
        // 同步抛错（如测试环境未 mock 该 API）同样按「无码」处理
        if (!cancelled) setFetched({})
      }
    }
    window.addEventListener('beforeprint', load)
    return () => {
      cancelled = true
      window.removeEventListener('beforeprint', load)
    }
  }, [provided])

  return provided ?? fetched ?? {}
}
