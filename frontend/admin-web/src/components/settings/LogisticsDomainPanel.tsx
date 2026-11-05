'use client'

import { useEffect, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { waybillApi } from '@/lib/api-waybill'
import { carrierSummary, emptyCapabilities } from '@/lib/waybill'
import { toastRequestError } from '@/lib/api-error'
import { SELECT_CONTROL } from '@/components/ui'
import type { WaybillCapabilities } from '@/types/waybill'

/**
 * 设置页「物流取号」域面板（issue #8698 P0；`/settings?domain=logistics`）。
 *
 * ## 它回答一个问题
 *
 * 「这家店发货时默认走哪家承运商、它今天能不能自动取号」——**只有这一个问题**（域内不再套导航）。
 *
 * ## 🔴 能力位来自服务端注册表，本组件不写任何承运商名
 *
 * 下拉候选 = `waybillApi.getCapabilities()` 的 `carriers`（服务端注册表现取）；
 * 每一行的「能不能自动取号」= `carrierSummary()`（纯函数读 `canCreate`）。
 * 新增 / 下线一家承运商只改服务端 `CarrierCatalogue` ⇒ 本面板与发货页**同时**跟着变
 * （判据 `tests/unit/lib/waybill.test.ts` 的「注册表增删 ⇒ 能力位跟着变」组）。
 *
 * ## 三种状态必须分得开（同 `NotificationsDomainPanel` 的 #6663 口径）
 *
 * ① 读到 ⇒ 渲染下拉 + 每行能力；② 读失败 ⇒ **明说「读不到」**，不画成「全部手填」
 * （画成手填 = 让商家以为配置丢了 / 以为不用配）；③ 还没读完 ⇒ 只显示「读取中」。
 */
export default function LogisticsDomainPanel() {
  const [caps, setCaps] = useState<WaybillCapabilities | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [readError, setReadError] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const res = await waybillApi.getCapabilities()
        if (alive) setCaps(res.data.data ?? emptyCapabilities())
      } catch {
        // 🔴 读失败 ≠ 全手填：标记出来并**不画**「当前配置」那行（不谎报状态）
        if (alive) setReadError(true)
      } finally {
        if (alive) setLoaded(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  /** 变更即保存（与算料口径 / 通知开关同款：配置面点一下就该生效，不另设保存按钮）。 */
  const handleChange = async (value: string) => {
    setSaving(true)
    try {
      const res = await waybillApi.saveCarrier(value === '' ? null : value)
      setCaps(res.data.data ?? emptyCapabilities())
      const name = res.data.data?.effectiveCarrier?.displayName ?? '手填单号'
      toast.success(`发货承运商已切换为「${name}」`)
    } catch (e) {
      toastRequestError(e, '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (readError) {
    return (
      <div
        data-testid="settings-logistics-read-error"
        className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <span className="flex-1">
          物流取号设置读取失败 —— 可能是网络或服务暂时不可用。这不代表「没有配置」，请刷新页面后再看。
        </span>
      </div>
    )
  }

  if (!loaded) {
    return <p className="text-xs text-neutral-400">物流取号设置读取中…</p>
  }

  const carriers = caps?.carriers ?? []
  const selectable = carriers.filter((c) => c.code !== 'manual')
  const current = caps?.configuredCarrier ?? ''

  return (
    <div className="space-y-5">
      <div>
        <div className="text-sm font-medium text-neutral-700">发货承运商</div>
        <div className="text-xs text-neutral-500 mt-1">
          选一家承运商后，发货页会按它的能力决定能不能自动取号；没接入取号的承运商一律手填单号。
          取号只生成运单号，订单仍要人工点「确认发货」。
        </div>
        <div className="mt-3">
          <select
            aria-label="发货承运商"
            data-testid="settings-logistics-carrier-select"
            /* 域写面出口标记（issue #6825）：改选即保存（`handleChange`） */
            data-write-exit="logistics"
            value={current}
            disabled={saving}
            onChange={(e) => void handleChange(e.target.value)}
            className={`${SELECT_CONTROL} w-full max-w-xs`}
          >
            <option value="">不自动取号（全部手填）</option>
            {selectable.map((c) => (
              <option key={c.code} value={c.code}>
                {c.displayName}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <div className="text-sm font-medium text-neutral-700">承运商能力</div>
        <div className="text-xs text-neutral-500 mt-1">
          我们支持的承运商会自动出现在这里，并以它当前的真实能力为准。
        </div>
        <ul className="mt-2 divide-y divide-neutral-100 rounded-lg border border-neutral-200">
          {carriers.map((c) => (
            <li
              key={c.code}
              data-testid={`settings-logistics-carrier-${c.code}`}
              className="flex items-center justify-between px-4 py-2.5 text-sm"
            >
              <span className="text-neutral-800">{c.displayName}</span>
              <span
                data-testid={`settings-logistics-capability-${c.code}`}
                className={c.canCreate ? 'text-primary-700' : 'text-neutral-500'}
              >
                {carrierSummary(c)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
