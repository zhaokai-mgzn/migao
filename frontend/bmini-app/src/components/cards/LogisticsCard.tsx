import { View, Text } from '@tarojs/components'
import './LogisticsCard.scss'

interface TrackItem {
  time: string
  description?: string
  content?: string
}

interface LogisticsCardProps {
  data: {
    company?: string
    tracking_no?: string
    tracking_number?: string
    status?: string
    status_text?: string
    tracks?: TrackItem[]
    traces?: TrackItem[]
  }
}

/** 物流状态标签颜色 */
const STATUS_MAP: Record<string, { text: string; className: string }> = {
  in_transit: { text: '运输中', className: 'logistics-card__status--transit' },
  delivered: { text: '已签收', className: 'logistics-card__status--delivered' },
  out_for_delivery: { text: '派送中', className: 'logistics-card__status--transit' },
  picked: { text: '已揽收', className: 'logistics-card__status--transit' },
  pending: { text: '待发货', className: 'logistics-card__status--pending' },
  exception: { text: '异常', className: 'logistics-card__status--error' },
  returned: { text: '已退回', className: 'logistics-card__status--error' },
}

/** 格式化轨迹时间 */
function formatTrackTime(timeStr: string): string {
  if (!timeStr) return ''
  // 取 MM-DD HH:mm 部分
  const date = new Date(timeStr)
  if (Number.isNaN(date.getTime())) return timeStr
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hours}:${minutes}`
}

export default function LogisticsCard({ data }: LogisticsCardProps) {
  const trackingNo = data.tracking_no || data.tracking_number || ''
  const company = data.company || '快递公司'
  const statusInfo = STATUS_MAP[data.status || ''] || {
    text: data.status_text || data.status || '未知',
    className: 'logistics-card__status--pending',
  }
  // 兼容 tracks / traces 字段
  const tracks = data.tracks || data.traces || []

  return (
    <View className='logistics-card'>
      {/* 头部信息 */}
      <View className='logistics-card__header'>
        <View className='logistics-card__company-row'>
          <Text className='logistics-card__icon'>📦</Text>
          <Text className='logistics-card__company'>{company}</Text>
          <View className={`logistics-card__status ${statusInfo.className}`}>
            <Text className='logistics-card__status-text'>{statusInfo.text}</Text>
          </View>
        </View>
        <Text className='logistics-card__tracking'>运单号: {trackingNo}</Text>
      </View>

      {/* 时间轴 */}
      {tracks.length > 0 && (
        <View className='logistics-card__timeline'>
          {tracks.map((track, idx) => {
            const isFirst = idx === 0
            const isLast = idx === tracks.length - 1
            const desc = track.description || track.content || ''
            return (
              <View
                key={`track-${idx}`}
                className={`logistics-card__track ${isFirst ? 'logistics-card__track--active' : ''}`}
              >
                <View className='logistics-card__track-dot-col'>
                  <View
                    className={`logistics-card__track-dot ${isFirst ? 'logistics-card__track-dot--active' : ''}`}
                  />
                  {!isLast && <View className='logistics-card__track-line' />}
                </View>
                <View className='logistics-card__track-content'>
                  <Text className={`logistics-card__track-time ${isFirst ? 'logistics-card__track-time--active' : ''}`}>
                    {formatTrackTime(track.time)}
                  </Text>
                  <Text className={`logistics-card__track-desc ${isFirst ? 'logistics-card__track-desc--active' : ''}`}>
                    {desc}
                  </Text>
                </View>
              </View>
            )
          })}
        </View>
      )}
    </View>
  )
}
