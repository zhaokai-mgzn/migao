'use client'

/**
 * 收款码读取口（**单一实现**，issue #5651 抽取）—— 报价单（#4965）与销售单（#5651）
 * 的「扫码支付」块共用这一份。抽出来的理由与 `lib/order-amount.ts` 同因：
 * **同一件事实在两处各写一次 ⇒ 将来改一处、另一处静默不一致**，而纸面不一致 =
 * 客户扫了打不开的码。
 *
 * ## 口径（四条，都有实测理由）
 *
 * 1. **调用方给了 `provided` ⇒ 一律用它**（调用方 / 测试注入优先），连裁边都不做 ——
 *    注入的是真值，不是要去修饰的素材。
 * 2. **「要出纸 / 正在预览」时才取**（`options.active`）：本 hook 的宿主组件在订单详情页
 *    **常驻挂载**（屏幕态 `display:none`）。挂载即取会在每次打开详情页都发一次请求；
 *    更糟的是读端点要 `order:list`，而纸面也挂在用户**没有**该码的页面上 ——
 *    那会变成「一进页面弹一条 403」（与 `use-company-name.ts` 的 #7285 同族，同一个坑）。
 *    `active` 由宿主给：`inline`（预览层）或本次打印目标就是它。
 * 3. **打印前必须等到码**（issue #7536）：`usePrintDoc` 在 `window.print()` 之前
 *    `await` 同一份 Promise —— 旧实现只在 `beforeprint` 里发请求，而浏览器在
 *    `beforeprint` 派发完**当帧就做纸面快照**，异步请求根本来不及回来 ⇒ **第一次打印纸上没有码**
 *    （实测：`beforeprint` 当帧 img 数 0，1.5s 后才是 1）。Ctrl+P 仍靠 `beforeprint` 兜底。
 * 4. **失败 / 为空 / 无权限一律按「无码」**（返回 `{}`，不抛不弹 toast）——
 *    调用方据此**整块不出现**：🔴 **缺码不画假码**（#4965 / 洗水码同一条判据）。
 *    读端点权限 = `order:list`（issue #7225：销售也要打印带码报价单）。
 *
 * 另外：取回来的 `imageUrl` 会过一遍 `resolveImageUrl()`（历史域名规范化）。
 * **白边不在这里裁** —— 它在**上传时**就裁好了（issue #7536 的用户裁定「直接改成上传时裁」，
 * 见 `lib/qr-image.ts`）：渲染时裁要先跨域读 OSS 图，读不到像素就只能退回原图，口径不可预期。
 */
import { useEffect, useState } from 'react'
import { settingsApi } from '@/lib/api'
import { resolveImageUrl } from '@/lib/utils'
import type { PaymentQrcodeMap } from '@/types'

let cached: Promise<PaymentQrcodeMap> | null = null

/**
 * 取收款码（**模块级缓存**：一次会话至多一次请求）。
 *
 * 预览层与真单据是两个实例、打印与预览又是两个时点 —— 都从这里拿同一份，
 * 谁先触发谁负责发请求，其余人等同一个 Promise。
 */
export function loadPaymentQrcodesOnce(): Promise<PaymentQrcodeMap> {
  if (!cached) {
    cached = (async () => {
      try {
        const res = await settingsApi.getPaymentQrcodes()
        const raw = (res?.data?.data ?? {}) as PaymentQrcodeMap
        const entries = Object.entries(raw).map(
          ([type, qr]) => [type, { ...qr, imageUrl: resolveImageUrl(qr?.imageUrl) }] as const
        )
        return Object.fromEntries(entries) as PaymentQrcodeMap
      } catch {
        // 同步抛错（如测试环境未 mock 该 API）/ 无权限 / 网络失败 ⇒ 无码
        return {}
      }
    })()
  }
  return cached
}

/**
 * 已经**在取**的那份 Promise（没开始过 ⇒ `null`）。
 *
 * 给 `usePrintDoc` 用：打印前只等「宿主确实要的码」，**不**在这里发起新请求
 * （否则在洗水唛等没有人要码的页面上打印会凭空多一次可能 403 的请求）。
 */
export function peekPaymentQrcodes(): Promise<PaymentQrcodeMap> | null {
  return cached
}

/** 测试专用：清空模块级缓存（生产代码不调用；与 `use-company-name.ts` 同名口径） */
export function __resetPaymentQrcodesCache(): void {
  cached = null
}

export interface UsePaymentQrcodesOptions {
  /** 本次渲染**是否要出纸**（预览层 = `inline`；屏幕态常驻挂载 = `false`）——见口径 2 */
  active?: boolean
}

export function usePaymentQrcodes(
  provided?: PaymentQrcodeMap,
  options?: UsePaymentQrcodesOptions
): PaymentQrcodeMap {
  const active = options?.active ?? false
  const [fetched, setFetched] = useState<PaymentQrcodeMap | null>(null)

  useEffect(() => {
    if (provided !== undefined) return
    let alive = true
    const load = () => {
      void loadPaymentQrcodesOnce().then((map) => {
        if (alive) setFetched(map)
      })
    }
    // Ctrl+P / 浏览器菜单打印：不经过 usePrintDoc，只能靠 beforeprint 兜底
    //（这条路径拿不到「等到码」的保证，属浏览器事件语义的边界，见口径 3）
    window.addEventListener('beforeprint', load)
    if (active) load()
    return () => {
      alive = false
      window.removeEventListener('beforeprint', load)
    }
  }, [provided, active])

  return provided ?? fetched ?? {}
}
