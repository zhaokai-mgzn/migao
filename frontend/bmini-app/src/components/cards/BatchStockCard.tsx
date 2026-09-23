import { View, Text } from '@tarojs/components'
import './BatchStockCard.scss'

/**
 * 批次账 / 省料度量卡（米宝 B 端**移动**会话内）— issue #5188
 *
 * 与 B 端桌面 `frontend/admin-web/src/components/chat/BatchStockCard.tsx` **同口径、同分支**：
 * 一个工具四个只读读面，按工具回的 `action` 判别键分支。
 *
 * ## 🔴 口径纪律（本仓红线）
 *
 * - **不算数**：所有米数 / 金额 / 占比**原样渲染服务端值**，本卡只做显示与「无数据」区分
 *   （不在 Taro 侧重算 —— 重算就是第二份会漂的口径）。
 * - **不写死档位文案**：四档文案取服务端 `buckets[].label`；「快用尽」阈值取工具回的
 *   `filters.nearly_used_up_threshold_meters`。
 * - **空数据不冒充 0**：`null`/缺值 ⇒ 「无数据」；真 0 显示 0。
 *
 * ## 为什么 C 端 mini-app **没有**这张卡
 *
 * 契约按 persona 推导（`backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）：
 * 该工具声明 `product:list` ⇒ C 端恒不可达 ⇒ 只要求 B 端两端渲染。
 * 给 C 端加分支 = 永不命中的死 UI（反向契约判据专门拦这种）。
 */

const NO_DATA = '无数据'

/** 服务端数值 → 文案；`null`/缺值 ⇒ 无数据（**不回落 0**） */
function fmt(value: number | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === '') return NO_DATA
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return digits === 0 ? String(Math.round(num)) : num.toFixed(digits).replace(/\.?0+$/, '')
}

/** 占比（服务端给 0~1 的比；`null` ⇒ 无数据） */
function fmtShare(share: number | string | null | undefined): string {
  const num = Number(share)
  return share === null || share === undefined || Number.isNaN(num)
    ? NO_DATA
    : `${(num * 100).toFixed(1)}%`
}

function fmtMeters(meters: number | string | null | undefined): string {
  const text = fmt(meters)
  return text === NO_DATA ? NO_DATA : `${text} 米`
}

interface BatchStockCardProps {
  data: any
}

export default function BatchStockCard({ data }: BatchStockCardProps) {
  const action = data?.action

  if (action === 'batches') {
    const rows: any[] = data?.batches || []
    const filters = data?.filters || {}
    return (
      <View className='batch-stock-card'>
        <View className='batch-stock-card__header'>
          <Text className='batch-stock-card__title'>批次余量</Text>
          <Text className='batch-stock-card__hint'>
            {filters.nearly_used_up
              ? `快用尽（剩余 ≤ ${filters.nearly_used_up_threshold_meters} 米）`
              : data?.truncated
                ? `仅展示前 ${rows.length} 个`
                : ''}
          </Text>
        </View>
        {rows.length === 0 ? (
          <Text className='batch-stock-card__empty'>{NO_DATA}</Text>
        ) : (
          rows.map((row, index) => (
            <View key={row.batchNo || index} className='batch-stock-card__row'>
              <Text className='batch-stock-card__label'>
                {`${row.batchNo || NO_DATA}${row.dyeLot ? `（缸号 ${row.dyeLot}）` : ''}`}
              </Text>
              <Text className='batch-stock-card__value'>{`剩 ${fmtMeters(row.remainingMeters)}`}</Text>
            </View>
          ))
        )}
      </View>
    )
  }

  if (action === 'distribution') {
    const buckets: any[] = data?.buckets || []
    return (
      <View className='batch-stock-card'>
        <View className='batch-stock-card__header'>
          <Text className='batch-stock-card__title'>剩余量分布</Text>
          <Text className='batch-stock-card__hint'>
            {data?.totalBatches ? `共 ${data.totalBatches} 个批次` : ''}
          </Text>
        </View>
        {!data?.totalBatches ? (
          <Text className='batch-stock-card__empty'>{NO_DATA}</Text>
        ) : (
          buckets.map((bucket, index) => (
            <View key={bucket.key || index} className='batch-stock-card__row'>
              {/* 档位文案取自服务端 label（不自己写数字） */}
              <Text className='batch-stock-card__label'>{bucket.label || NO_DATA}</Text>
              <Text className='batch-stock-card__value'>
                {`${bucket.batchCount ?? 0} 个 · ${fmtShare(bucket.share)}`}
              </Text>
            </View>
          ))
        )}
      </View>
    )
  }

  if (action === 'saving_board') {
    const cohorts: any[] = data?.cohorts || []
    return (
      <View className='batch-stock-card'>
        <View className='batch-stock-card__header'>
          <Text className='batch-stock-card__title'>省料度量</Text>
          <Text className='batch-stock-card__hint'>
            {data?.granularity ? `按${data.granularity === 'week' ? '周' : '月'}` : ''}
          </Text>
        </View>
        {cohorts.map((cohort, index) => {
          const bucketLabel = cohort?.buckets?.[0]?.label
          const saved = cohort?.savedMeters
          return (
            <View key={cohort.cohort || index} className='batch-stock-card__group'>
              <Text className='batch-stock-card__group-title'>
                {cohort.cohortLabel || cohort.cohort || NO_DATA}
              </Text>
              <View className='batch-stock-card__row'>
                <Text className='batch-stock-card__label'>省料</Text>
                <Text className='batch-stock-card__value'>
                  {saved === null || saved === undefined
                    ? NO_DATA
                    : `${fmtMeters(saved)} / ${fmt(cohort.savedAmount)} 元`}
                </Text>
              </View>
              <View className='batch-stock-card__row'>
                <Text className='batch-stock-card__label'>
                  {bucketLabel ? `剩余 ${bucketLabel} 的批次占比` : '剩余最小档的批次占比'}
                </Text>
                <Text className='batch-stock-card__value'>{fmtShare(cohort.le0_2Share)}</Text>
              </View>
            </View>
          )
        })}
        <Text className='batch-stock-card__hint'>
          {`合计省 ${fmtMeters(data?.total?.savedMeters)} / ${fmt(data?.total?.savedAmount)} 元`}
        </Text>
      </View>
    )
  }

  if (action === 'saving_trend') {
    return (
      <View className='batch-stock-card'>
        <View className='batch-stock-card__header'>
          <Text className='batch-stock-card__title'>省料趋势</Text>
          <Text className='batch-stock-card__hint'>
            {data?.granularity ? `按${data.granularity === 'week' ? '周' : '月'}` : ''}
          </Text>
        </View>
        <View className='batch-stock-card__row'>
          <Text className='batch-stock-card__label'>采购入库</Text>
          <Text className='batch-stock-card__value'>{fmtMeters(data?.purchasedTotalMeters)}</Text>
        </View>
        <View className='batch-stock-card__row'>
          <Text className='batch-stock-card__label'>消耗</Text>
          <Text className='batch-stock-card__value'>{fmtMeters(data?.consumedTotalMeters)}</Text>
        </View>
        <View className='batch-stock-card__row'>
          {/* 存量导入单列（它不是「这个月的采购」） */}
          <Text className='batch-stock-card__label'>存量导入入库（单列）</Text>
          <Text className='batch-stock-card__value'>{fmtMeters(data?.openingTotalMeters)}</Text>
        </View>
      </View>
    )
  }

  return (
    <View className='batch-stock-card'>
      <Text className='batch-stock-card__title'>批次 / 省料</Text>
      <Text className='batch-stock-card__empty'>{NO_DATA}</Text>
    </View>
  )
}
