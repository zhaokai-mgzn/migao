'use client'

/**
 * 销售订单列表 · **行内快捷发货**录入区（issue #8013，B 端体验打磨 P1：列表即队列）。
 *
 * ## 为什么要它
 *
 * 看板「待发货 49 单」，而每单发货都要「点行内『发货』→ 跳到 `/orders/{id}/ship` 整页 → 填表 →
 * 提交 → 回列表」= **49 次页面往返**，每次都要重新定位上一单在哪。商家实际是「连着录运单号」，
 * 不是「一单一趟出远门」。⇒ 录入区展开在**该行下方**（不是整页跳转、也不是遮罩模态），
 * 提交成功后收起、列表原地刷新，接着处理下一单。
 *
 * ## 写面：复用**既有**原子端点，不改后端
 *
 * 提交走 `productionApi.shipOrder`（`POST /api/admin/production/orders/{id}/ship`，issue #6983）——
 * 它在**单事务**里做三件事：记物流 + 原子流转 `shipped` + 建可查的发货单（`order_shipments`），
 * 且认 `X-Client-Request-Id` 幂等。
 *
 * ⛔ **不得改走 `PUT /api/admin/orders/{id}/logistics`**（issue #8013 派单时曾这么写，已订正）：
 * 那条路**只写 `order_logistics` 一行、不翻转 `orders.status`** ⇒ 提交成功后列表仍显示「待发货」，
 * 商家会把同一单再录一遍，而 `order_shipments` 永远 0 行。若将来要把它接成发货入口，
 * 必须先解决状态流转（那是**另一个**决定，不在本组件射程）。
 *
 * ## 前端预校验与服务端**同口径**
 *
 * 只有**显式** `shippingMethod=logistics` 且运单号为空时才拦（服务端同一条规则，issue #6239）；
 * `none`（无需物流）本来就没有单号 ⇒ 直接提交。「保留原运单号」的编辑路径不在本组件射程
 * （那是订单详情的「编辑物流」弹窗，走 `LogisticsForm`），此处的空单号拦截**不会**误伤它。
 *
 * ## 失败态
 *
 * 4xx/5xx ⇒ 录入区**保留**、输入**原样保留**、错误文案**在行内**（服务端原文优先，
 * `extractApiErrorMessage`）；不弹一个独占屏幕的 toast，也不假装成功去刷新列表。
 *
 * ## 收起后焦点归位（issue #8027）
 *
 * 本组件只管「收起」（`onClose` / `onShipped`），**焦点**由宿主 `OrderTable` 还给触发这一行的
 * 「发货」按钮 —— 提交成功 / `Escape` / 「取消」三条路径一致，且**不用焦点陷阱库**。
 * ⛔ 别在这里自己 `focus()`：录入区内的按钮在收起时就卸载了，抢不到落点。
 */
import { useEffect, useRef, useState } from 'react'
import { Button, SELECT_CONTROL_FIELD } from '@/components/ui'
import FormPanel, { Field, FormGrid, fieldControl } from '@/components/ui/FormPanel'
import { productionApi } from '@/lib/api'
import { extractApiErrorMessage } from '@/lib/api-error'
import { newClientRequestId } from '@/lib/client-request-id'
import { LOGISTICS_COMPANIES } from '@/lib/logistics'
import { useAuthStore } from '@/store/auth'
import type { OrderBrief } from '@/types'

export interface InlineShipFormProps {
  /** 要发货的那一单（列表行形态 —— 这里只用到 `id`，不读详情报文） */
  order: OrderBrief
  /** 收起录入区（取消 / `Escape` / 再次点「发货」都走这里） */
  onClose: () => void
  /** 提交成功：由页面收起录入区并**按既有方式刷新列表**（真值来自服务端，不做乐观改写） */
  onShipped: () => void
}

export default function InlineShipForm({ order, onClose, onShipped }: InlineShipFormProps) {
  // 发货人默认当前登录人（与发货页同一条兜底链：**不**退化成「管理员」——那是角色名不是人名）
  const currentUser = useAuthStore((s) => s.user)
  const defaultShipperName = currentUser?.name || currentUser?.nickname || currentUser?.username || ''

  const [shippingMethod, setShippingMethod] = useState<'logistics' | 'none'>('logistics')
  const [logisticsCompany, setLogisticsCompany] = useState<string>(LOGISTICS_COMPANIES[0])
  const [trackingNo, setTrackingNo] = useState('')
  const [shipperName, setShipperName] = useState(defaultShipperName)
  const [shipperTouched, setShipperTouched] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  /** 幂等键（口径见 `src/lib/client-request-id.ts`）；`null` = 下一件发货是新事 */
  const requestIdRef = useRef<string | null>(null)

  // 登录用户信息可能晚于首屏到达：仅在用户还没动过该字段时回填，不覆盖手工输入
  useEffect(() => {
    if (!shipperTouched && defaultShipperName) setShipperName(defaultShipperName)
  }, [defaultShipperName, shipperTouched])

  // `Escape` 收起 —— 与行内「⋯」菜单同一口径：键盘可达，不把录入区做成只能靠鼠标关的陷阱
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const handleSubmit = async () => {
    if (submitting) return
    // 🔴 与**服务端**同口径（issue #6239 / #8013）：只在「显式物流发货 + 运单号为空」时拦。
    if (shippingMethod === 'logistics' && !trackingNo.trim()) {
      setError('请输入快递单号')
      return
    }
    setError('')
    setSubmitting(true)
    const clientRequestId = requestIdRef.current ?? newClientRequestId()
    requestIdRef.current = clientRequestId
    try {
      await productionApi.shipOrder(
        order.id,
        {
          // 「无需物流」不填单号/承运商（服务端按 shippingMethod 分流，允许为空）
          company: shippingMethod === 'logistics' ? logisticsCompany : '',
          trackingNo: shippingMethod === 'logistics' ? trackingNo.trim() : '',
          shippingMethod,
          shipperName: shipperName.trim(),
        },
        clientRequestId,
      )
      // 成功 ⇒ 作废本次幂等键（下一件发货是新事）
      requestIdRef.current = null
      onShipped()
    } catch (e) {
      // 失败 ⇒ **保留**该键：重试复用同值，服务端同键回放，不会发两次货
      setError(extractApiErrorMessage(e, '发货失败，请稍后重试'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <FormPanel
      testid="ship-inline-form"
      title="快捷发货"
      hint="运单号录完直接提交 —— 不跳页，可以接着录下一单。整单有特殊情况时可去发货页处理。"
      className="max-w-5xl"
    >
      <FormGrid cols={4}>
        <Field label="物流方式" htmlFor={`ship-method-${order.id}`}>
          <select
            id={`ship-method-${order.id}`}
            className={`w-full ${SELECT_CONTROL_FIELD}`}
            value={shippingMethod}
            disabled={submitting}
            onChange={(e) => {
              setShippingMethod(e.target.value as 'logistics' | 'none')
              setError('')
            }}
          >
            <option value="logistics">物流发货</option>
            <option value="none">无需物流</option>
          </select>
        </Field>

        {shippingMethod === 'logistics' && (
          <>
            <Field label="物流公司" htmlFor={`ship-company-${order.id}`}>
              <select
                id={`ship-company-${order.id}`}
                className={`w-full ${SELECT_CONTROL_FIELD}`}
                value={logisticsCompany}
                disabled={submitting}
                onChange={(e) => {
                  setLogisticsCompany(e.target.value)
                  setError('')
                }}
              >
                {LOGISTICS_COMPANIES.map((company) => (
                  <option key={company} value={company}>
                    {company}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="运单号" htmlFor={`ship-tracking-${order.id}`}>
              <input
                id={`ship-tracking-${order.id}`}
                className={fieldControl()}
                value={trackingNo}
                placeholder="请输入运单号"
                disabled={submitting}
                aria-invalid={error ? true : undefined}
                onChange={(e) => {
                  setTrackingNo(e.target.value)
                  setError('')
                }}
              />
            </Field>
          </>
        )}

        <Field label="发货人" htmlFor={`ship-shipper-${order.id}`}>
          <input
            id={`ship-shipper-${order.id}`}
            data-testid="ship-inline-shipper"
            className={fieldControl()}
            value={shipperName}
            placeholder="按实际经手人修改"
            disabled={submitting}
            onChange={(e) => {
              setShipperName(e.target.value)
              setShipperTouched(true)
            }}
          />
        </Field>
      </FormGrid>

      <div className="mt-3 flex items-center gap-2">
        {/* 表格行内的主行动 + 次级动作 ⇒ 一律 `sm`（§32.2：行内 / 面板头的小动作） */}
        <Button size="sm" type="button" onClick={() => void handleSubmit()} loading={submitting}>
          确认发货
        </Button>
        <Button size="sm" type="button" variant="secondary" onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <span className="text-xs text-neutral-400">发货后订单自动转为「已发货」</span>
      </div>

      {error !== '' && (
        <p data-testid="ship-inline-error" role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
    </FormPanel>
  )
}
