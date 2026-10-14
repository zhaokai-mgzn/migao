// case_ids: BM-040
/**
 * 加工单详情（**商家只读面**，issue #6567）
 *
 * ## 为什么有这一页
 * 「数据」页的三类待办（待排产 / 卡在哪 / 待发货）原先一律落到**报工页**
 * （`/pages/production/index/index`，已于 2026-10-14 随 issue #6868 实现包 D1 下架）
 * —— 那页是**工人面**：顶部「扫一扫 + 手输单号」，
 * 没有工人身份时还整块渲染「去登录工人身份」。商家点一张待办卡片看到的是「请先登录工人身份」，
 * 而他要的是「这一单什么情况」（用户 2026-10-08 反馈）。
 *
 * ## 三条纪律
 * ① **纯只读**：本页没有任何写入口、也不发任何写请求 —— 不扫码、不报工、不发货
 *    （写面在电脑端与工人端；判据见 tests/processing-order-detail-page.test.tsx 的第 3 条）；
 * ② **显示名不自拼**：工序名走唯一口径 `operationDisplayName`（`逻辑名 · 部位`），
 *    与 worker-h5 同源（原报工页已下架，见上）；
 * ③ **三态不混淆**：`无权限(403)` / `这笔订单还没有加工单` / `加载失败` 分开说 ——
 *    把 403 渲染成「没有数据」就是把「看不到」说成「没有」（同「数据」页的三态口径）。
 *
 * ## 为什么补「商品身份 / 规格尺寸 / 加工信息」（issue #6901 包 B）
 * 用户 2026-10-14 逐字「加工单缺乏订单中的规格尺寸和加工信息，**工人需要这些信息+商品信息**
 * 来决定如何生产」—— 本页原先只有「单号 + 工序进度 + 卡在哪」，工人看不到做的是哪一件、
 * 按什么规格做。现在**逐部位**多三块，与既有的逐部位进度/卡点**同层**。
 *
 * 展示**不新造标签表**：加工信息走 `utils/craft-display.ts::craftSpecRows()` —— 它与
 * admin-web / mini-app **逐字同源**（守卫 `tests/unit_ci_workflows/test_craft_display_same_source.py`
 * 判 C1 逐字节相等），因此「标签与 admin-web 单一真值漂移」在仓内**进不来**。
 *
 * 缺值口径不变（沿用上面第一条与 §4.9）：**缺值不渲染那一行**，绝不出现
 * `undefined` / `null` / `NaN`，也不补默认值（缺键 = 未携带，不是错值）。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import {
  getOrderOperations,
  getProcessingOrderBrief,
  type OrderOperations,
  type ProcessingOrderBrief,
} from '../../../services/productionService'
import {
  getStuckPoints,
  stuckThresholdSourceLabel,
  type StuckPointRow,
} from '../../../services/stuckPointService'
import { operationDisplayName } from '../../../utils/operationDisplayName'
import { resolveOrderIdFromParams } from '../../../utils/productionQr'
import { craftSpecRows } from '../../../utils/craft-display'
import { sellingMethodLabel } from '../../../utils/selling-method'
import './index.scss'

type PageState = 'loading' | 'ok' | 'missing-id' | 'forbidden' | 'no-processing-order' | 'error'

/** 权限文案与电脑端同口径（权限码真值在后端 `@RequirePermission`） */
const PERMISSION_TEXT = '无「生产看板」查看权限（需要权限码 production:view）'

/**
 * 「商品身份」组的行（issue #6901 包 B）：品名 / 货号 / 颜色 / 售卖方式 / 单位。
 *
 * 键名口径与**服务端加工单快照**（`ProcessingOrderService.buildSnapshot` 的逐键透传）一致 ——
 * 部位规格面（`ProductionService.orderSpecByItemId`）由包 A 补齐同族键；缺键即该行不渲染。
 */
const IDENTITY_FIELDS: Array<{ label: string; resolve: (source: Record<string, unknown>) => string | null }> = [
  { label: '品名', resolve: (source) => text(pick(source, ['product_name', 'productName'])) },
  { label: '货号', resolve: (source) => text(pick(source, ['sku', 'skuCode'])) },
  { label: '颜色', resolve: (source) => text(pick(source, ['colorName', 'color_name'])) },
  // 售卖方式落库的是**内部键**（`bulk_cut` / `full_roll`）⇒ 走展示名单一口径，不把内部键摆上屏
  {
    label: '售卖方式',
    resolve: (source) => sellingMethodLabel(pick(source, ['sellingMethod', 'selling_method'])),
  },
  // 计量单位（合同组 1 的「数量 + 单位」）；数量属于**工序**行、这里只印单位，缺键不渲染
  { label: '单位', resolve: (source) => text(pick(source, ['unit'])) },
]

/**
 * 加工信息块里**不重复印**的标签。
 *
 * 只剔「部位」（`curtainType`）—— 它**已经**是本部位那一块的标题（`position_name` 就是部位名），
 * 同一屏再印一行「部位：布帘」是同一真值印两遍（`migao-dev-flow` §31 P2）。
 * ⚠️ 「门幅」**不剔**：商品身份组没有自己的门幅栏 ⇒ 剔了它门幅就**一次都不显示**
 * （而门幅是工人下料要核的尺寸，issue #6901 组 3 明确要它）。
 */
const OWN_LABELS = new Set(['部位'])

/** 键别名取第一个「存在且非 null/undefined」的值（与 craft-display 的 `pick` 同语义；本页只读标量） */
function pick(source: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = source[key]
    if (value !== undefined && value !== null) return value
  }
  return undefined
}

/** 标量文本：空串 / 空白 / 数组 / 对象 / 布尔 ⇒ `null`（该行不渲染，不摆占位） */
function text(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() === '' ? null : value.trim()
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null
  return null
}

/**
 * 规格尺寸（宽 × 高，单位米）：`3.20 × 2.75 米`。
 *
 * 仓内米数展示口径是**两位小数 + 单位**（`craft-display.ts::meters` 的 `3.2米` 是「原值 + 米」，
 * 因为它吃的是门幅那种已格式化原串；宽高来自 `order_items` 的 `BigDecimal` 列 ⇒ 这里按两位小数摆齐）。
 * 只为**在场**的那一维出数（缺一维 ⇒ 只印一维，绝不印 `3.20 × 米`/`NaN`）；两维都缺 ⇒ `null`。
 */
function sizeText(width: unknown, height: unknown): string | null {
  const dim = (value: unknown): string | null => {
    const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN
    return Number.isFinite(n) ? n.toFixed(2) : null
  }
  const parts = [dim(width), dim(height)].filter((part): part is string => part !== null)
  return parts.length > 0 ? `${parts.join(' × ')} 米` : null
}

/**
 * 派工（批号 + 指派米数）：**两键都在才显示** —— 缺键 = 未指派，不是缺数据
 * （口径见 `ProductionService.stampBatchAssignments` 与 `ProductionPosition` 的字段注释）。
 */
function batchText(no: unknown, meters: unknown): string | null {
  const batchNo = text(no)
  if (batchNo === null) return null
  const m = typeof meters === 'number' ? meters : typeof meters === 'string' ? Number(meters) : NaN
  if (!Number.isFinite(m)) return null
  return `${batchNo} · ${m} 米`
}

export default function ProcessingOrderDetailPage() {
  // 参数解析走唯一口径（`order_id` / `orderId` / 单号 / 二维码 token 逐个试；解不出 ⇒ null，不瞎猜）
  const [orderId] = useState<string | null>(() =>
    resolveOrderIdFromParams(Taro.getCurrentInstance().router?.params),
  )
  const [state, setState] = useState<PageState>('loading')
  const [order, setOrder] = useState<ProcessingOrderBrief | null>(null)
  const [detail, setDetail] = useState<OrderOperations | null>(null)
  const [opsFailed, setOpsFailed] = useState(false)
  // 「卡在哪」卡点面（issue #6597）：与工序进度**各自独立** —— 卡点面挂了只少一块，
  // 不把整页判成失败（口径见 tests/processing-order-detail-stuck.test.tsx 判据 5）。
  const [stuck, setStuck] = useState<StuckPointRow[] | null>(null)
  const [stuckFailed, setStuckFailed] = useState(false)
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    if (!orderId) {
      setState('missing-id')
      return
    }
    setState('loading')
    // 卡点面**先发**（只读、不依赖抬头）：它单独失败不影响整页三态。
    const stuckRes = await getStuckPoints(orderId)
    setStuck(stuckRes.status === 'ok' ? (stuckRes.data.stuck ?? []) : null)
    setStuckFailed(stuckRes.status !== 'ok')
    const brief = await getProcessingOrderBrief(orderId)
    if (brief.forbidden) {
      setState('forbidden')
      return
    }
    if (!brief.success) {
      setMessage(brief.message || '加载失败，请重试')
      setState('error')
      return
    }
    if (!brief.data) {
      setState('no-processing-order')
      return
    }
    setOrder(brief.data)
    const ops = await getOrderOperations(orderId)
    // issue #6573 顺带修：原写法 `ops.success && ops.data ? ops.data : null` 命中
    // `frontend/admin-web/tests/unit/components/NumberInputWiring.test.ts` 判据 ⑧
    //（全仓零命中的「falsy 兜底」形态：`x ? x : null` 这种把**取值**与**真值判断**糅在一句里的写法，
    // 一旦载荷变成 `0`/`''` 就会静默丢掉它）⇒ 拆成显式的 `?? null`；语义逐值不变
    //（`ops.data` 是对象，除 null/undefined 外都为真）。
    const opsData = ops.success ? (ops.data ?? null) : null
    setDetail(opsData)
    setOpsFailed(opsData === null)
    setState('ok')
  }, [orderId])

  useEffect(() => {
    void load()
  }, [load])

  const progress = detail?.progress
  const positions = detail?.positions || []
  // 缺键的行**不渲染**（不补默认值、不摆 '—' 占位）—— 页头只放商家真的能读到的字段
  const headerRows: Array<[string, string]> = order
    ? ([
        ['加工单号', order.processingOrderNo],
        ['订单号', order.orderNo],
        ['客户', order.customerName],
        ['交期', order.expectedDeliveryDate],
      ].filter(([, value]) => !!value) as Array<[string, string]>)
    : []
  // 卡点块：**没有卡点 ⇒ 整块不渲染**（不摆「暂无卡点」空壳）。阈值取**服务端下发的那个数**
  // （不在前端另立一份：换口径会与 web 面 / 待办面漂移）。
  const stuckThreshold = stuck?.[0]?.threshold_hours ?? null

  return (
    <ScrollView scrollY className='order-detail'>
      {state === 'loading' && (
        <Text className='order-detail__hint' data-testid='order-detail-loading'>
          加载中…
        </Text>
      )}

      {state === 'missing-id' && (
        <Text className='order-detail__hint' data-testid='order-detail-missing-id'>
          没带加工单参数 —— 请从「数据」页的待办点进来
        </Text>
      )}

      {state === 'forbidden' && (
        <Text className='order-detail__hint' data-testid='order-detail-forbidden'>
          {PERMISSION_TEXT}
        </Text>
      )}

      {state === 'no-processing-order' && (
        <Text className='order-detail__hint' data-testid='order-detail-no-processing-order'>
          这笔订单还没有加工单
        </Text>
      )}

      {state === 'error' && (
        <View className='order-detail__error'>
          <Text className='order-detail__hint' data-testid='order-detail-error'>
            {message || '加载失败，请重试'}
          </Text>
          <Button className='order-detail__retry' onClick={load}>
            重试
          </Button>
        </View>
      )}

      {state === 'ok' && order && (
        <>
          <View className='order-detail__card' data-testid='order-detail-header'>
            {headerRows.map(([label, value]) => (
              <View key={label} className='order-detail__row'>
                <Text className='order-detail__label'>{label}</Text>
                <Text className='order-detail__value'>{value}</Text>
              </View>
            ))}
          </View>

          {/* 商品身份 / 规格尺寸 / 加工信息（issue #6901 包 B）：**逐部位**一块，与下面的
              逐部位工序进度同层。缺值的行整行不渲染（不补默认值、不摆占位）。 */}
          {positions.length > 0 && (
            <View className='order-detail__card' data-testid='order-detail-specs'>
              <Text className='order-detail__section'>商品与加工信息</Text>
              <Text className='order-detail__spec-hint'>工人按这里的信息备料、下料</Text>
              {positions.map((position) => {
                const source = position as unknown as Record<string, unknown>
                const identityRows: Array<[string, string]> = []
                for (const field of IDENTITY_FIELDS) {
                  const value = field.resolve(source)
                  if (value !== null) identityRows.push([field.label, value])
                }
                const craftRows = craftSpecRows(source).filter((row) => !OWN_LABELS.has(row.label))
                const size = sizeText(source.width, source.height)
                const batch = batchText(source.batch_no, source.batch_meters)
                const remark = text(source.remark)
                const spec: Array<[string, string]> = [
                  ...(size === null ? [] : ([['规格尺寸', size]] as Array<[string, string]>)),
                  ...craftRows.map((row) => [row.label, row.value] as [string, string]),
                ]
                return (
                  <View
                    key={position.order_item_id ?? position.position_name}
                    className='order-detail__position'
                    data-testid='order-detail-position-spec'
                  >
                    <Text className='order-detail__position-name'>{position.position_name}</Text>
                    {identityRows.map(([label, value]) => (
                      <View key={label} className='order-detail__row'>
                        <Text className='order-detail__label'>{label}</Text>
                        <Text className='order-detail__value'>{value}</Text>
                      </View>
                    ))}
                    {spec.map(([label, value]) => (
                      <View key={label} className='order-detail__row'>
                        <Text className='order-detail__label'>{label}</Text>
                        <Text className='order-detail__value'>{value}</Text>
                      </View>
                    ))}
                    {batch !== null && (
                      <View className='order-detail__row'>
                        <Text className='order-detail__label'>派工</Text>
                        <Text className='order-detail__value'>{batch}</Text>
                      </View>
                    )}
                    {remark !== null && (
                      <View className='order-detail__row'>
                        <Text className='order-detail__label'>备注</Text>
                        <Text className='order-detail__value'>{remark}</Text>
                      </View>
                    )}
                  </View>
                )
              })}
            </View>
          )}

          <View className='order-detail__card' data-testid='order-detail-operations'>
            <Text className='order-detail__section'>工序进度</Text>
            {progress && (
              <Text className='order-detail__progress' data-testid='order-detail-progress'>
                {`已完成 ${progress.done}/${progress.total}`}
              </Text>
            )}
            {opsFailed && <Text className='order-detail__hint'>工序进度没加载出来 —— 再进本页试一次</Text>}
            {!opsFailed && positions.length === 0 && (
              <Text className='order-detail__hint'>本单还没有工序（还没排产）</Text>
            )}
            {positions.map((position) => (
              <View key={position.position_name} className='order-detail__position'>
                <Text className='order-detail__position-name'>{position.position_name}</Text>
                {position.operations.map((operation) => (
                  <View key={operation.id} className='order-detail__operation'>
                    <Text className='order-detail__operation-name'>
                      {operationDisplayName(operation)}
                    </Text>
                    <Text className='order-detail__operation-meta'>
                      {`应做 ${operation.qty}${operation.unit} · 已报 ${operation.done_qty}${operation.unit}`}
                    </Text>
                  </View>
                ))}
              </View>
            ))}
          </View>

          {/* 「卡在哪」（issue #6597）：判据本体在服务端（`GET /api/admin/production/stuck-points`），
              本页**只渲染** —— 谁卡了 / 等了多久 / 阈值多少 / 阈值从哪来，一个数都不自己算。
              常驻面克制：抬头一句（条数 + 阈值 + 来源），逐条明细各一行、不随条数长成告警墙。 */}
          {stuck && stuck.length > 0 && (
            <View className='order-detail__card' data-testid='order-detail-stuck'>
              <Text className='order-detail__section'>卡在哪</Text>
              <Text className='order-detail__stuck-summary'>
                {`这单有 ${stuck.length} 道卡住了（上道已交、这道没人开工，等待超过 ${stuckThreshold} 小时就列在这里；${stuckThresholdSourceLabel(stuck[0]?.threshold_source)}）`}
              </Text>
              {stuck.map((row) => (
                <View
                  key={`${row.set_id ?? ''}-${row.operation?.operation_id ?? ''}`}
                  className='order-detail__stuck-row'
                  data-testid='order-detail-stuck-row'
                >
                  <Text className='order-detail__stuck-op'>
                    {operationDisplayName(row.operation) || '这道工序'}
                  </Text>
                  <Text className='order-detail__stuck-wait'>{`等了 ${row.stalled_hours} 小时`}</Text>
                </View>
              ))}
            </View>
          )}
          {stuckFailed && (
            <Text className='order-detail__hint' data-testid='order-detail-stuck-hint'>
              卡在哪没加载出来 —— 再进本页试一次
            </Text>
          )}
        </>
      )}
    </ScrollView>
  )
}
