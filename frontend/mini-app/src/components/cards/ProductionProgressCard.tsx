import { View, Text } from '@tarojs/components'
import './ProductionProgressCard.scss'

/** 工序（内部字段如 unit_price/worker_name 不参与渲染） */
interface ProductionCardOperation {
  id?: string
  operation: string
  status?: string
}

interface ProductionCardPosition {
  position_name: string
  operations?: ProductionCardOperation[]
}

interface ProductionCardData {
  order_id?: string
  order_no?: string
  status?: string
  status_text?: string
  positions?: ProductionCardPosition[]
  operations?: ProductionCardOperation[]
  progress?: { total?: number; done?: number; percent?: number }
  /** 米宝精简进度载荷（GET /api/admin/agent/production/progress?order_no=）字段 */
  progress_percent?: number
  current_operation?: string
  pending_operations?: string[]
  total_operations?: number
  done_operations?: number
  /** 预计交付日期（ISO 或 YYYY-MM-DD；缺省则不渲染该行） */
  expected_delivery_at?: string
  expected_delivery_date?: string
  delivery_date?: string
}

interface ProductionProgressCardProps {
  data: ProductionCardData
}

/** 取日期部分（后端可能下发 ISO 时间戳） */
function formatDate(value: string): string {
  return value.slice(0, 10)
}

/** 拍平工序列表（positions[].operations[] 优先，兼容扁平 operations[]） */
function flattenOperations(
  positions: ProductionCardPosition[],
  flat?: ProductionCardOperation[],
): ProductionCardOperation[] {
  if (flat && flat.length > 0) return flat
  const result: ProductionCardOperation[] = []
  positions.forEach((position) => {
    ;(position.operations || []).forEach((operation) => result.push(operation))
  })
  return result
}

/**
 * 顾客端生产进度卡（issue #3997，M4-G-3）
 *
 * 只给顾客看**进度 / 当前工序 / 待完工序数 / 预计交付**；
 * 工人姓名、计件单价、成本、二维码 token 等内部信息一律不渲染
 * （两套账分离：内部计件 vs 对外加工费，真值源 docs/curtain-production-rules.md §4）。
 *
 * 兼容两种载荷（两者字段名不同，缺一不可）：
 * 1. 工序树：{positions[].operations[], progress:{total,done,percent}, expected_delivery_at}
 * 2. 米宝精简进度：{progress_percent, current_operation, pending_operations[],
 *    total_operations, done_operations, expected_delivery_date}
 */
export default function ProductionProgressCard({ data }: ProductionProgressCardProps) {
  const positions = data?.positions || []
  const operations = flattenOperations(positions, data?.operations)

  const pendingList = data?.pending_operations
  const doneFromOps = operations.filter((operation) => operation.status === 'done').length
  const total = data?.progress?.total ?? data?.total_operations ?? operations.length
  const done = data?.progress?.done ?? data?.done_operations ?? doneFromOps
  const percent =
    data?.progress?.percent
    ?? data?.progress_percent
    ?? (total > 0 ? Math.round((done / total) * 100) : 0)

  const currentFromOps = operations.find((operation) => operation.status !== 'done')
  const current = data?.current_operation || currentFromOps?.operation
  const remaining = pendingList
    ? pendingList.length
    : operations.filter((operation) => operation.status !== 'done').length
  const delivery =
    data?.expected_delivery_at || data?.expected_delivery_date || data?.delivery_date

  // 两种载荷都没带工序信息才是空态（精简载荷没有工序树，但有 current/pending 计数）
  const hasDetail =
    operations.length > 0 || !!current || (pendingList?.length ?? 0) > 0 || total > 0

  return (
    <View className='production-progress-card'>
      <View className='production-progress-card__header'>
        <Text className='production-progress-card__title'>生产进度</Text>
        <Text className='production-progress-card__percent'>{`${percent}%`}</Text>
      </View>

      <View className='production-progress-card__track'>
        <View
          className='production-progress-card__fill'
          style={{ width: `${percent}%` }}
        />
      </View>

      {!hasDetail ? (
        <Text className='production-progress-card__empty'>暂无生产进度</Text>
      ) : (
        <>
          <Text className='production-progress-card__row'>{`已完 ${done}/${total} 道`}</Text>
          {current && (
            <Text className='production-progress-card__row'>{`当前工序：${current}`}</Text>
          )}
          <Text className='production-progress-card__row'>{`待完 ${remaining} 道工序`}</Text>
        </>
      )}

      {delivery && (
        <Text className='production-progress-card__delivery'>{`预计交付 ${formatDate(delivery)}`}</Text>
      )}
    </View>
  )
}
