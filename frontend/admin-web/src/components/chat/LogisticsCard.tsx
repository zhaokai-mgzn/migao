'use client'

import { Truck, CheckCircle, Clock, MapPin } from 'lucide-react'
import { cn } from '@/lib/utils'

interface LogisticsCardProps {
  data: Record<string, unknown>
}

export default function LogisticsCard({ data }: LogisticsCardProps) {
  const tracking = (data.tracking_info as Record<string, unknown>) || data
  const trackingNo = (tracking.trackingNo as string) || (tracking.tracking_no as string) || ''
  const company = (tracking.company as string) || ''
  const status = (tracking.status as string) || ''
  const tracks = (tracking.tracks as Array<Record<string, unknown>>) || []

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      {/* 头部 */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100">
        <Truck className="w-4 h-4 text-blue-600" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-800">
            {company || '物流信息'}
          </p>
          {trackingNo && (
            <p className="text-[10px] text-gray-500 mt-0.5">
              运单号: {trackingNo}
            </p>
          )}
        </div>
        {status && (
          <span className="text-[10px] px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full font-medium">
            {status}
          </span>
        )}
      </div>

      {/* 物流时间线 */}
      {tracks.length > 0 && (
        <div className="px-3 py-2 max-h-48 overflow-y-auto">
          <div className="space-y-0">
            {tracks.slice(0, 5).map((track, index) => {
              const isFirst = index === 0
              return (
                <div key={index} className="flex gap-2.5 relative">
                  {/* 时间线 */}
                  <div className="flex flex-col items-center flex-shrink-0">
                    <div
                      className={cn(
                        'w-2 h-2 rounded-full mt-1.5',
                        isFirst ? 'bg-blue-500' : 'bg-gray-300'
                      )}
                    />
                    {index < tracks.length - 1 && index < 4 && (
                      <div className="w-px flex-1 bg-gray-200 my-1" />
                    )}
                  </div>

                  {/* 内容 */}
                  <div className="pb-3 min-w-0 flex-1">
                    <p
                      className={cn(
                        'text-xs leading-relaxed',
                        isFirst ? 'text-gray-800 font-medium' : 'text-gray-500'
                      )}
                    >
                      {(track.description as string) || ''}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {(track.time as string) || ''}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {tracks.length === 0 && (
        <div className="px-3 py-4 text-center text-xs text-gray-400">
          暂无物流轨迹
        </div>
      )}
    </div>
  )
}
