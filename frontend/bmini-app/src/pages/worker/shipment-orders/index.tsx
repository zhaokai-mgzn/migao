/**
 * 工人**待发货单**列表（issue #7806 P1a）—— `/b/` 工人工作台新增的一条入口（只读）。
 *
 * ## 这一页回答什么
 *
 * 「车间今天能发哪些单」。数据源 = `GET /api/worker/shipment/orders`
 * （#7764 上线；`WorkerShipmentReadyService.listReadyOrders`）—— 服务端只回
 * **多套全部完工 + 可发货状态 + 作业单已完成**的订单，行内带收货信息与物流类型 / 公司。
 *
 * ## 四条纪律（每条都有对应断言，见 `tests/worker-shipment-orders-page.test.tsx`）
 *
 * 1. 🔴 **前端不筛、不补算**：服务端给几行就渲染几行；半完工行（`completed_sets < total_sets`）
 *    照实显示 `1/3 套`，**不得**显示成「全完工」，也**不得**被前端丢掉 ——
 *    前端自己再筛一遍就是第二份完工口径（与 H5 `/w/` 那一份迟早分叉）。
 * 2. 🔴 **三态互斥、各有稳定 testID**：读取中 / 读不到（可重试）/ 没有单。
 *    「读不到」**不得**渲染成「暂无」—— 那是两个事实（前者可能只是网差，工人据此决定要不要等）。
 * 3. 🔴 **401 单独一态**：未登录 / 会话失效 ⇒ 引导去工人登录，不清商家态、不跳商家登录页
 *    （工人端点的 401 不是「商家会话过期」，见 `utils/request.ts` 的身份分流口径）。
 * 4. 🔴 **内部值不上屏**：物流类型只用 `logistics_type_label`（`express` / `logistics` 是内部值）；
 *    缺值一律 `—`（不印 0、不猜「快递」）。
 *
 * ## 边界（照实登记）
 *
 * - **发货联（整套出库单）预览 + 50×70 打印**（issue #8287）：行清单 = `utils/labels/shipLabel.ts`，
 *   与 H5 `/w/` 的 `buildShipLabelRows` **同源**（判据 `tests/ship-label-rows-parity.test.ts` 现取两侧实现比对）；
 *   打印走共享行式标签通道（小程序 BLE / 手持终端 / 浏览器蓝牙，经 `createPrintTransport`）。
 * - 本页**仍然不发货**（没有写入口）：发货的写路径在 H5 `/w/` 与端内「拍照发货」
 *   （`POST /api/worker/shipment/orders/{id}/ship`）；本页**不**新增第二条发货写路径。
 * - 列表没有关键词筛选 / 分页：服务端按最新在前截断并回 `scan.truncated`，本页只负责把它说出来。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { fetchCurrentWorker } from '../../../services/workerService'
import { listReadyShipmentOrders } from '../../../services/workerShipmentOrdersService'
import { SHIPMENT_ORDERS_WORKER_LOGIN_REQUIRED, WORKER_TAB_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
import { clearWorkerSession, hasWorkerSession, type CurrentWorker } from '../../../utils/workerSession'
import type { ReadyShipmentOrder, ReadyShipmentOrdersPage } from '../../../services/workerShipmentOrdersService'
// 发货联（50×70）预览 / 打印：行清单与 `/w/` 同源；送打印只走共享入口（不在页面里碰 transport）。
import { buildShipLabelRows, shipLabelSpec } from '../../../utils/labels/shipLabel'
import { renderRowsLabel } from '../../../utils/labels/rowsLabel'
import { createH5CanvasFactory, SDK_UNAVAILABLE_HINT } from '../../../utils/inbound/labelPageKit'
import { printRowsLabel } from '../../../utils/inbound/labelPrint'
import { probePrintCapability } from '../../../utils/inbound/printCapability'
import { createPrintTransport } from '../../../utils/inbound/terminalTransport'
import './index.scss'

/** 缺值占位符（与 H5 发货页 / 发货单纸面同口径：**不是** 0、不是空串、不是「未知」）。 */
export const MISSING = '—'

/** 空态文案（含「怎么才会有单」——只说「没有」等于没说）。 */
export const EMPTY_HINT = '暂无全部完工的订单：最后一道工序报完后，这一单会自动出现在这里'

/** 读不到时的兜底文案（技术原文留在请求层，屏上只出现人话）。 */
export const READ_FAILED_HINT = '读取失败，请重试'

/** 页面上的四种状态（互斥）。 */
export type ShipmentOrdersPhase = 'loading' | 'error' | 'unauthorized' | 'ready'

/** 文本化：`null` / 空串 / 纯空白 ⇒ `—`（缺值不编造）。 */
export function textOrMissing(value: unknown): string {
  const text = value == null ? '' : String(value).trim()
  return text === '' ? MISSING : text
}

/**
 * 套数文案（**只读服务端读数**，不在前端数）。
 *
 * - `completed === total` ⇒ `N 套（全完工）`
 * - 否则 ⇒ `1/3 套`（半完工照实说 —— 服务端理论上不会给这种行，但前端不许把它"修好"）
 * - `total` 缺 / ≤0 ⇒ `—`
 */
export function setsText(order: ReadyShipmentOrder | null | undefined): string {
  const total = Number(order?.total_sets)
  const completed = Number(order?.completed_sets)
  if (!Number.isFinite(total) || total <= 0) return MISSING
  // 完成数缺值 ⇒ 整格 `—`（**不许**补 0：「0/3」是在替服务端断言「一套都没做完」）
  if (!Number.isFinite(completed)) return MISSING
  if (completed === total) return `${total} 套（全完工）`
  return `${completed}/${total} 套`
}

/**
 * 物流类型一行：`物流类型标签 · 公司`；两侧都缺 ⇒ `—`（**不**回退成「快递」）。
 *
 * ⚠️ 用词是「物流类型」（= `logistics_type`，快递 / 物流专线），**不是**「物流方式」
 * （那是 `shippingMethod`：物流发货 / 无需物流）—— 两个列撞词会让工人读错行（issue #8071）。
 */
export function logisticsText(order: ReadyShipmentOrder | null | undefined): string {
  const parts = [order?.logistics_type_label, order?.logistics_company]
    .map((part) => (part == null ? '' : String(part).trim()))
    .filter((part) => part !== '')
  return parts.length > 0 ? parts.join(' · ') : MISSING
}

/** 一行订单卡（`data-testid` 逐字段带序号：判据按它定位，不按文案）。 */
function OrderRow({
  order,
  index,
  onPreview,
}: {
  order: ReadyShipmentOrder
  index: number
  onPreview: (order: ReadyShipmentOrder) => void
}) {
  return (
    <View className='shipment-orders__row' data-testid={`shipment-orders-row-${index}`}>
      <Text className='shipment-orders__no' data-testid={`shipment-orders-no-${index}`}>
        {textOrMissing(order.order_no)}
      </Text>
      <Text className='shipment-orders__line' data-testid={`shipment-orders-consignee-${index}`}>
        收货人：{textOrMissing(order.customer_name)}　电话：{textOrMissing(order.customer_phone)}
      </Text>
      <Text
        className='shipment-orders__line shipment-orders__addr'
        data-testid={`shipment-orders-address-${index}`}
      >
        地址：{textOrMissing(order.customer_address)}
      </Text>
      <Text className='shipment-orders__line' data-testid={`shipment-orders-logistics-${index}`}>
        物流类型：{logisticsText(order)}
      </Text>
      <Text className='shipment-orders__line' data-testid={`shipment-orders-sets-${index}`}>
        套数：{setsText(order)}
      </Text>
      <Button
        className='shipment-orders__label-open'
        data-testid={`shipment-orders-label-${index}`}
        onClick={() => onPreview(order)}
      >
        发货联
      </Button>
    </View>
  )
}

export default function WorkerShipmentOrdersPage() {
  /** 本机有没有工人身份（本地判据，只决定「去读」还是「先引导登录」） */
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<CurrentWorker | null>(null)
  const [phase, setPhase] = useState<ShipmentOrdersPhase>(workerReady ? 'loading' : 'unauthorized')
  const [page, setPage] = useState<ReadyShipmentOrdersPage | null>(null)
  const [message, setMessage] = useState('')
  /** 正在预览 / 待打印的那张发货联（`null` = 收起） */
  const [labelOrder, setLabelOrder] = useState<ReadyShipmentOrder | null>(null)
  const [printBusy, setPrintBusy] = useState(false)
  const [labelNotice, setLabelNotice] = useState('')

  const load = useCallback(async () => {
    if (!workerReady) {
      setPhase('unauthorized')
      return
    }
    setPhase('loading')
    setMessage('')
    const res = await listReadyShipmentOrders()
    if (res.success && res.data) {
      setPage(res.data)
      setPhase('ready')
      return
    }
    // 🔴 401 = 未登录 / 会话失效 ⇒ 只清本机工人身份并引导登录；
    //    **不**渲染成「读不到」或「没有单」（三种事实各有各的出口）。
    if (res.statusCode === 401) {
      clearWorkerSession()
      setWorker(null)
      setPhase('unauthorized')
      return
    }
    setMessage(res.message || READ_FAILED_HINT)
    setPhase('error')
  }, [workerReady])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!workerReady) return
    // 页头「当前工人」取自服务端（与工作台同源）；读不到不阻塞列表（列表才是本页的正事）
    void fetchCurrentWorker().then((res) => {
      if (res.success && res.data) setWorker(res.data)
    })
  }, [workerReady])

  const goWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  /** 打印能力（动手前就说清本机能不能打）。 */
  const printCapability = useMemo(() => probePrintCapability(), [])

  const openLabel = useCallback((order: ReadyShipmentOrder) => {
    setLabelOrder(order)
    setLabelNotice('')
  }, [])

  const closeLabel = useCallback(() => {
    setLabelOrder(null)
    setLabelNotice('')
  }, [])

  /**
   * 打印发货联（50×70 整套出库单）。
   *
   * 行清单只取本行服务端字段；版面 / 渲染 / 送打印走共享件。本页**不发货** ——
   * 发货联是**出库单纸面**，不改库存、不调 ship 端点（写路径仍在拍照发货 / PC 发货）。
   */
  const printShipLabel = useCallback(
    async (order: ReadyShipmentOrder) => {
      setLabelNotice('')
      if (!printCapability.ok) {
        setLabelNotice(printCapability.hint)
        return
      }
      setPrintBusy(true)
      try {
        const transport = await createPrintTransport()
        if (!transport) {
          setLabelNotice(SDK_UNAVAILABLE_HINT)
          return
        }
        const result = await printRowsLabel({
          capability: printCapability,
          transport,
          render: () => renderRowsLabel(shipLabelSpec(order), createH5CanvasFactory()),
        })
        setLabelNotice(result.ok ? `已送出打印（${result.transportLabel}）` : result.hint)
      } catch {
        // 通道加载 / 连接异常：给可行动文案，不把未捕获异常留给工人
        setLabelNotice(SDK_UNAVAILABLE_HINT)
      } finally {
        setPrintBusy(false)
      }
    },
    [printCapability],
  )

  const items = page?.items ?? []
  const count = items.length
  const truncated = page?.scan?.truncated === true

  return (
    <View className='shipment-orders'>
      <View className='shipment-orders__header'>
        <View className='shipment-orders__heading'>
          <Text className='shipment-orders__title'>待发货单</Text>
          {worker && phase !== 'unauthorized' ? (
            <Text className='shipment-orders__worker' data-testid='shipment-orders-worker'>
              当前工人：{textOrMissing(worker.worker_name)}
            </Text>
          ) : null}
        </View>
        <Button
          className='shipment-orders__refresh'
          data-testid='shipment-orders-refresh'
          onClick={() => {
            void load()
          }}
        >
          刷新
        </Button>
      </View>

      {phase === 'loading' ? (
        <View className='shipment-orders__notice' data-testid='shipment-orders-loading'>
          <Text className='shipment-orders__notice-text'>正在读取待发货单…</Text>
        </View>
      ) : null}

      {phase === 'unauthorized' ? (
        <View className='shipment-orders__gate' data-testid='shipment-orders-login-required'>
          <Text className='shipment-orders__gate-text'>{SHIPMENT_ORDERS_WORKER_LOGIN_REQUIRED}</Text>
          <Button
            className='shipment-orders__login'
            data-testid='shipment-orders-login'
            onClick={goWorkerLogin}
          >
            去登录工人身份
          </Button>
        </View>
      ) : null}

      {phase === 'error' ? (
        <View className='shipment-orders__notice' data-testid='shipment-orders-error'>
          <Text className='shipment-orders__notice-text'>{message || READ_FAILED_HINT}</Text>
          <Button
            className='shipment-orders__retry'
            data-testid='shipment-orders-retry'
            onClick={() => {
              void load()
            }}
          >
            重试
          </Button>
        </View>
      ) : null}

      {phase === 'ready' ? (
        <View className='shipment-orders__body'>
          <Text className='shipment-orders__count' data-testid='shipment-orders-count'>
            待发货 {count} 单（全部套已完工）
          </Text>
          {count === 0 ? (
            <View className='shipment-orders__notice' data-testid='shipment-orders-empty'>
              <Text className='shipment-orders__notice-text'>{EMPTY_HINT}</Text>
            </View>
          ) : (
            <View className='shipment-orders__list' data-testid='shipment-orders-list'>
              {items.map((order, index) => (
                <OrderRow
                  key={order.order_id || `row-${index}`}
                  order={order}
                  index={index}
                  onPreview={openLabel}
                />
              ))}
            </View>
          )}
          {truncated ? (
            <Text className='shipment-orders__truncated' data-testid='shipment-orders-truncated'>
              还有更多单未列出，发完再来刷新
            </Text>
          ) : null}

          {labelOrder ? (
            <View className='shipment-orders__label' data-testid='shipment-orders-label-preview'>
              <Text className='shipment-orders__label-title' data-testid='shipment-orders-label-title'>
                发货联 · {textOrMissing(labelOrder.order_no)}
              </Text>
              <View className='shipment-orders__label-rows' data-testid='shipment-orders-label-rows'>
                {buildShipLabelRows(labelOrder).map((row) => (
                  <View key={row.key} className='shipment-orders__label-row'>
                    <Text className='shipment-orders__label-key'>{row.label}</Text>
                    <Text className='shipment-orders__label-value'>{row.value}</Text>
                  </View>
                ))}
              </View>
              <Text className='shipment-orders__label-hint' data-testid='shipment-orders-label-capability'>
                {printCapability.ok ? printCapability.readyHint : printCapability.hint}
              </Text>
              <View className='shipment-orders__label-actions'>
                <Button
                  className='shipment-orders__label-print'
                  data-testid='shipment-orders-label-print'
                  disabled={!printCapability.ok || printBusy}
                  onClick={() => {
                    void printShipLabel(labelOrder)
                  }}
                >
                  {printBusy ? '打印中…' : '打印发货联（50×70）'}
                </Button>
                <Button
                  className='shipment-orders__label-close'
                  data-testid='shipment-orders-label-close'
                  onClick={closeLabel}
                >
                  收起
                </Button>
              </View>
              {labelNotice ? (
                <Text className='shipment-orders__label-notice' data-testid='shipment-orders-label-notice'>
                  {labelNotice}
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  )
}
