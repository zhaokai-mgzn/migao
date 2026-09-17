import { useCallback, useState } from 'react'
import { View, Text, Button, Input, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import {
  getOrderOperations,
  reportOperation,
  type OrderOperations,
  type ProductionOperation,
} from '../../../services/productionService'
import { parseOrderIdFromQr } from '../../../utils/productionQr'
import './index.scss'

/** 计件单价展示（元，工序库口径；两位小数） */
function formatPrice(value: number | string): string {
  return Number(value || 0).toFixed(2)
}

/**
 * 工人端扫码报工（issue #3997，M4-G-3）
 *
 * 链路：扫一扫 / 手输单号 → 本单工序（按部位分组，含应做数量/单位/单价）
 *   → 「完成报工」（qty 默认 = 应做数量，work_type=normal）→ 刷新进度
 *   → 必完工序全绿 → 「✅ 订单生产完成」。
 * 报工失败只展示后端 message，**不清空列表**（工人可继续报其它工序）。
 */
export default function ProductionPage() {
  const { user } = useAuthStore()
  const [detail, setDetail] = useState<OrderOperations | null>(null)
  const [manualId, setManualId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [orderCompleted, setOrderCompleted] = useState(false)

  /** 拉取工序列表（扫码成功 / 手输查单共用） */
  const loadOrder = useCallback(async (rawId: string) => {
    const orderId = (rawId || '').trim()
    if (!orderId) {
      Taro.showToast({ title: '请输入加工单号', icon: 'none' })
      return
    }
    setLoading(true)
    setError('')
    const res = await getOrderOperations(orderId)
    setLoading(false)
    if (!res.success || !res.data) {
      setError(res.message || '未找到该加工单，请确认单号')
      return
    }
    setDetail(res.data)
    setManualId(orderId)
  }, [])

  /** 扫一扫（失败/无相机时走手输单号兜底） */
  const handleScan = useCallback(async () => {
    try {
      const res = await Taro.scanCode({ scanType: ['qrCode'] })
      const orderId = parseOrderIdFromQr(res?.result || '')
      if (!orderId) {
        Taro.showToast({ title: '无法识别该二维码，请手动输入单号', icon: 'none' })
        return
      }
      await loadOrder(orderId)
    } catch {
      Taro.showToast({ title: '扫码未完成，请手动输入单号', icon: 'none' })
    }
  }, [loadOrder])

  /** 完成报工（数量默认 = 该工序应做数量） */
  const handleReport = useCallback(
    async (operation: ProductionOperation) => {
      if (!detail) return
      setError('')
      const res = await reportOperation(detail.order_id, operation.id, {
        worker_id: user?.id || '',
        worker_name: user?.nickname || '',
        qty: operation.qty,
        qualified_qty: operation.qty,
        work_type: 'normal',
      })
      if (!res.success) {
        setError(res.message || '报工失败，请重试')
        return
      }
      if (res.data?.order_completed) {
        setOrderCompleted(true)
      }
      // 复用同一入口刷新进度（报工成功才刷新）
      await loadOrder(detail.order_id)
    },
    [detail, user, loadOrder],
  )

  const positions = detail?.positions || []
  const progress = detail?.progress
  const percent = progress?.percent ?? 0
  const isCompleted =
    orderCompleted || (!!progress && progress.total > 0 && progress.done >= progress.total)

  return (
    <ScrollView scrollY className='production-page'>
      {/* 顶部：扫一扫 + 手输单号兜底 */}
      <View className='production-scan-bar'>
        <Button className='production-scan-bar__btn' onClick={handleScan}>
          扫一扫
        </Button>
        <Text className='production-scan-bar__hint'>扫描加工单二维码，自动带出本单工序</Text>
      </View>

      <View className='production-manual'>
        <Input
          className='production-manual__input'
          value={manualId}
          placeholder='或手输加工单号'
          onInput={(event) => setManualId(event.detail.value)}
        />
        <Button className='production-manual__btn' onClick={() => loadOrder(manualId)}>
          查单
        </Button>
      </View>

      {error !== '' && (
        <View className='production-error'>
          <Text className='production-error__text'>{error}</Text>
        </View>
      )}

      {loading && (
        <View className='production-loading'>
          <Text>加载工序中...</Text>
        </View>
      )}

      {!loading && !detail && (
        <View className='production-empty'>
          <Text>扫码或输入加工单号后显示本单工序</Text>
        </View>
      )}

      {detail && (
        <View className='production-detail'>
          {/* 进度 */}
          <View className='production-progress'>
            <Text className='production-progress__text'>
              {`已完 ${progress?.done ?? 0}/${progress?.total ?? 0} 道 · ${percent}%`}
            </Text>
            <View className='production-progress__track'>
              <View className='production-progress__fill' style={{ width: `${percent}%` }} />
            </View>
          </View>

          {isCompleted && (
            <View className='production-completed'>
              <Text className='production-completed__text'>✅ 订单生产完成</Text>
            </View>
          )}

          {/* 工序列表（按部位分组） */}
          {positions.map((position) => (
            <View key={position.position_name} className='production-position'>
              <Text className='production-position__name'>{position.position_name}</Text>
              {position.operations.map((operation) => (
                <View key={operation.id} className='operation-item'>
                  <View className='operation-item__body'>
                    <Text className='operation-item__name'>{operation.operation}</Text>
                    <Text className='operation-item__meta'>
                      {`应做 ${operation.qty}${operation.unit} · ¥${formatPrice(operation.unit_price)}`}
                    </Text>
                    <Text className='operation-item__done'>
                      {`已报 ${operation.done_qty}${operation.unit}`}
                    </Text>
                  </View>
                  <Button className='operation-item__btn' onClick={() => handleReport(operation)}>
                    完成报工
                  </Button>
                </View>
              ))}
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  )
}
