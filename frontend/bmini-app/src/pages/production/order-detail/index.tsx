// case_ids: BM-040
/**
 * 加工单详情（**商家只读面**，issue #6567）
 *
 * ## 为什么有这一页
 * 「数据」页的三类待办（待排产 / 卡在哪 / 待发货）原先一律落到**报工页**
 * （`/pages/production/index/index`）—— 那页是**工人面**：顶部「扫一扫 + 手输单号」，
 * 没有工人身份时还整块渲染「去登录工人身份」。商家点一张待办卡片看到的是「请先登录工人身份」，
 * 而他要的是「这一单什么情况」（用户 2026-10-08 反馈）。
 *
 * ## 三条纪律
 * ① **纯只读**：本页没有任何写入口、也不发任何写请求 —— 不扫码、不报工、不发货
 *    （写面在电脑端与工人端；判据见 tests/processing-order-detail-page.test.tsx 的第 3 条）；
 * ② **显示名不自拼**：工序名走唯一口径 `operationDisplayName`（`逻辑名 · 部位`），
 *    与报工页 / worker-h5 同源；
 * ③ **三态不混淆**：`无权限(403)` / `这笔订单还没有加工单` / `加载失败` 分开说 ——
 *    把 403 渲染成「没有数据」就是把「看不到」说成「没有」（同「数据」页的三态口径）。
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
import { operationDisplayName } from '../../../utils/operationDisplayName'
import { resolveOrderIdFromParams } from '../../../utils/productionQr'
import './index.scss'

type PageState = 'loading' | 'ok' | 'missing-id' | 'forbidden' | 'no-processing-order' | 'error'

/** 权限文案与电脑端同口径（权限码真值在后端 `@RequirePermission`） */
const PERMISSION_TEXT = '无「生产看板」查看权限（需要权限码 production:view）'

export default function ProcessingOrderDetailPage() {
  // 参数解析走唯一口径（`order_id` / `orderId` / 单号 / 二维码 token 逐个试；解不出 ⇒ null，不瞎猜）
  const [orderId] = useState<string | null>(() =>
    resolveOrderIdFromParams(Taro.getCurrentInstance().router?.params),
  )
  const [state, setState] = useState<PageState>('loading')
  const [order, setOrder] = useState<ProcessingOrderBrief | null>(null)
  const [detail, setDetail] = useState<OrderOperations | null>(null)
  const [opsFailed, setOpsFailed] = useState(false)
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    if (!orderId) {
      setState('missing-id')
      return
    }
    setState('loading')
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
        </>
      )}
    </ScrollView>
  )
}
